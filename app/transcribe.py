#!/usr/bin/env python3
"""Transcribe a WAV file with Whisper.

Supports both openai-whisper and faster-whisper backends.

Loaded models stay cached between dictations and are released after
BLITZTEXT_MODEL_CACHE_SECONDS of inactivity (default 600; 0 disables caching
and reloads the model for every call).
"""
from __future__ import annotations

import base64
import gc
import json
import logging
import os
import sys
import threading
import urllib.error
import urllib.request
import warnings
import wave
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("blitztext.transcribe")

VALID_MODEL_NAMES = {
    "tiny", "base", "small", "medium",
    "large", "large-v2", "large-v3", "large-v3-turbo",
}
VALID_BACKENDS = {"openai-whisper", "faster-whisper", "openrouter", "openai-cloud"}
DEFAULT_OPENROUTER_TRANSCRIBE_MODEL = "openai/gpt-4o-transcribe"
DEFAULT_OPENAI_CLOUD_TRANSCRIBE_MODEL = "gpt-4o-transcribe"
_OPENROUTER_TRANSCRIPTIONS_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
_CLOUD_REQUEST_TIMEOUT = 45.0
# A WAV with only its header carries no samples (e.g. an accidental short press).
_WAV_HEADER_BYTES = 44
# As in the original Blitztext app: vocabulary hints only for recordings of at
# least 0.9 s. On very short audio Whisper tends to echo the initial prompt
# ("Eigennamen und Begriffe: ...") instead of transcribing.
_HINT_MIN_SECONDS = 0.9
# AudioRecorder writes 16 kHz mono s16le; used when the header has no frame count.
_FALLBACK_BYTES_PER_SECOND = 16000 * 2
_MODEL_CACHE_ENV = "BLITZTEXT_MODEL_CACHE_SECONDS"
_MODEL_CACHE_DEFAULT_SECONDS = 600.0

_model_cache: dict[tuple, Any] = {}
_model_cache_lock = threading.Lock()
_model_unload_timer: Optional[threading.Timer] = None


class TranscribeError(Exception):
    """Raised when transcription fails (missing dep, bad file, model error)."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def transcribe(
    wav_file: Path | str,
    model: str = "base",
    language: str = "de",
    backend: str = "openai-whisper",
    custom_terms: list[str] | None = None,
    api_key: str = "",
) -> str:
    """Transkribiert eine WAV-Datei und gibt den Text zurueck.

    Args:
        wav_file: Pfad zur WAV-Datei (16 kHz, mono).
        model:    Whisper-Modellname (z. B. 'base', 'small') oder Cloud-Modell-ID.
        language: Sprachcode ('de', 'en', ...) oder 'auto' fuer Autodetect.
        backend:  'openai-whisper' | 'faster-whisper' | 'openrouter' | 'openai-cloud'
        custom_terms: Optionale Eigennamen/Fachbegriffe als Transkriptions-Hint.
        api_key:  Optionaler API-Schluessel fuer Cloud-Backends (Fallback: Env).

    Returns:
        Transkribierter Text (stripped). Leer wenn nichts erkannt.

    Raises:
        TranscribeError: Bei fehlender Abhaengigkeit, fehlendem File oder
                         Modell-Fehler.
    """
    wav_file = Path(wav_file).resolve()

    if backend not in VALID_BACKENDS:
        raise TranscribeError(
            f"Ungültiger Backend {backend!r}. Gültig: {sorted(VALID_BACKENDS)}"
        )
    if backend in {"openai-whisper", "faster-whisper"} and model not in VALID_MODEL_NAMES:
        raise TranscribeError(
            f"Ungültiger Modellname {model!r}. Gültig: {sorted(VALID_MODEL_NAMES)}"
        )
    if not wav_file.is_file():
        raise TranscribeError(f"WAV-Datei nicht gefunden: {wav_file}")
    if wav_file.stat().st_size <= _WAV_HEADER_BYTES:
        raise TranscribeError(f"WAV-Datei enthält keine Audiodaten: {wav_file}")

    if custom_terms and _wav_duration_seconds(wav_file) < _HINT_MIN_SECONDS:
        logger.debug("Recording shorter than %.1fs; transcribing without vocabulary hint", _HINT_MIN_SECONDS)
        custom_terms = None

    try:
        hint = _build_transcription_hint(custom_terms)
        hotwords = _build_hotwords(custom_terms)
        if backend == "openrouter":
            return _transcribe_openrouter(str(wav_file), model, language, hint=hint, api_key=api_key)
        if backend == "openai-cloud":
            return _transcribe_openai_cloud(str(wav_file), model, language, hint=hint, api_key=api_key)
        if backend == "faster-whisper":
            return _transcribe_faster(str(wav_file), model, language, hint=hint, hotwords=hotwords)
        return _transcribe_openai(str(wav_file), model, language, hint=hint)
    except TranscribeError:
        raise
    except ImportError as exc:
        raise TranscribeError(str(exc)) from exc
    except Exception as exc:
        raise TranscribeError(f"Transkription fehlgeschlagen: {exc}") from exc


# ---------------------------------------------------------------------------
# Model cache
# ---------------------------------------------------------------------------

def _model_cache_idle_seconds() -> float:
    raw = os.environ.get(_MODEL_CACHE_ENV, "")
    if not raw.strip():
        return _MODEL_CACHE_DEFAULT_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning("Invalid %s=%r, using %.0fs", _MODEL_CACHE_ENV, raw, _MODEL_CACHE_DEFAULT_SECONDS)
        return _MODEL_CACHE_DEFAULT_SECONDS


def _schedule_model_unload(idle_seconds: float) -> None:
    """(Re)start the idle timer. Caller must hold ``_model_cache_lock``."""
    global _model_unload_timer
    if _model_unload_timer is not None:
        _model_unload_timer.cancel()
    timer = threading.Timer(idle_seconds, unload_cached_models)
    timer.daemon = True
    timer.start()
    _model_unload_timer = timer


def _get_model(key: tuple, loader: Callable[[], Any]) -> Any:
    """Return a cached model for ``key`` or load it; only one model stays resident."""
    idle_seconds = _model_cache_idle_seconds()
    if idle_seconds <= 0:
        return loader()
    with _model_cache_lock:
        model = _model_cache.get(key)
        if model is None:
            if _model_cache:
                _model_cache.clear()
                gc.collect()
            model = loader()
            _model_cache[key] = model
            logger.info("Whisper model loaded and cached: %s", key)
        _schedule_model_unload(idle_seconds)
    return model


def unload_cached_models() -> None:
    """Drop cached models so their RAM/VRAM can be released."""
    global _model_unload_timer
    with _model_cache_lock:
        had_models = bool(_model_cache)
        _model_cache.clear()
        if _model_unload_timer is not None:
            _model_unload_timer.cancel()
            _model_unload_timer = None
    if had_models:
        gc.collect()
        logger.info("Cached Whisper model released after idle timeout")


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------

def _wav_duration_seconds(wav_file: Path) -> float:
    try:
        with wave.open(str(wav_file), "rb") as wav:
            frames, rate = wav.getnframes(), wav.getframerate()
        if frames > 0 and rate > 0:
            return frames / rate
    except (wave.Error, EOFError, OSError):
        pass
    try:
        size = wav_file.stat().st_size
    except OSError:
        return 0.0
    return max(0, size - _WAV_HEADER_BYTES) / _FALLBACK_BYTES_PER_SECOND


def _normalize_language(language: str) -> Optional[str]:
    return None if not language or language == "auto" else language


def _clean_custom_terms(custom_terms: list[str] | None) -> list[str]:
    if not custom_terms:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for term in custom_terms:
        if not isinstance(term, str):
            continue
        cleaned = term.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _build_transcription_hint(custom_terms: list[str] | None) -> str | None:
    cleaned = _clean_custom_terms(custom_terms)
    if not cleaned:
        return None
    return "Eigennamen und Begriffe: " + ", ".join(cleaned)


def _build_hotwords(custom_terms: list[str] | None) -> str | None:
    cleaned = _clean_custom_terms(custom_terms)
    if not cleaned:
        return None
    return ", ".join(cleaned)


def _should_force_cpu_for_openai() -> bool:
    return os.environ.get("WHISPER_USE_CUDA", "").lower() not in {"1", "true", "yes"}


def _load_openai_whisper_module():
    try:
        import whisper  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "openai-whisper nicht installiert. Bitte: pipx install openai-whisper"
        ) from exc
    return whisper


def _load_faster_whisper_model_class():
    try:
        from faster_whisper import WhisperModel  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "faster-whisper nicht installiert. Bitte: pipx inject openai-whisper faster-whisper"
        ) from exc
    return WhisperModel


def _transcribe_openai(wav_file: str, model_name: str, language: str, hint: str | None = None) -> str:
    warnings.filterwarnings("ignore", message="FP16 is not supported on CPU")
    original_cuda_visible_devices = os.environ.get("CUDA_VISIBLE_DEVICES")
    should_force_cpu = _should_force_cpu_for_openai()
    if should_force_cpu:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    try:
        whisper = _load_openai_whisper_module()

        model = _get_model(
            ("openai-whisper", model_name, should_force_cpu),
            lambda: whisper.load_model(model_name),
        )
        result = model.transcribe(
            wav_file,
            language=_normalize_language(language),
            initial_prompt=hint,
        )
    finally:
        if should_force_cpu:
            if original_cuda_visible_devices is None:
                os.environ.pop("CUDA_VISIBLE_DEVICES", None)
            else:
                os.environ["CUDA_VISIBLE_DEVICES"] = original_cuda_visible_devices
    if not isinstance(result, dict):
        logger.warning("Transcription result is not a dict: %r", type(result).__name__)
        return ""
    text = result.get("text")
    if not isinstance(text, str):
        logger.warning("Transcription result missing 'text' key or wrong type: %r", result)
        return ""
    return text.strip()


def _transcribe_faster(
    wav_file: str,
    model_name: str,
    language: str,
    hint: str | None = None,
    hotwords: str | None = None,
) -> str:
    WhisperModel = _load_faster_whisper_model_class()

    hf_cache = os.path.expanduser("~/.cache/huggingface/hub")
    os.makedirs(hf_cache, exist_ok=True)

    model = _get_model(
        ("faster-whisper", model_name),
        lambda: WhisperModel(model_name, device="auto", compute_type="int8"),
    )
    segments, _ = model.transcribe(
        wav_file,
        language=_normalize_language(language),
        initial_prompt=hint,
        hotwords=hotwords,
    )
    parts = [getattr(seg, "text", "") for seg in segments]
    return " ".join(parts).strip()


def _resolve_openrouter_model(model_name: str) -> str:
    cleaned = (model_name or "").strip()
    if not cleaned or cleaned in VALID_MODEL_NAMES:
        return DEFAULT_OPENROUTER_TRANSCRIBE_MODEL
    if "/" not in cleaned:
        return f"openai/{cleaned}"
    return cleaned


def _resolve_openai_cloud_model(model_name: str) -> str:
    cleaned = (model_name or "").strip()
    if not cleaned or cleaned in VALID_MODEL_NAMES:
        return DEFAULT_OPENAI_CLOUD_TRANSCRIBE_MODEL
    if cleaned.startswith("openai/"):
        return cleaned.split("/", 1)[1]
    return cleaned


def _transcribe_openrouter(
    wav_file: str,
    model_name: str,
    language: str,
    hint: str | None = None,
    api_key: str = "",
) -> str:
    effective_key = (
        api_key.strip()
        or os.environ.get("OPENROUTER_API_KEY", "").strip()
    )
    if not effective_key:
        raise TranscribeError(
            "OpenRouter API-Key nicht gesetzt. Bitte OPENROUTER_API_KEY in "
            "~/.config/blitztext-linux/secrets.env setzen."
        )
    target_model = _resolve_openrouter_model(model_name)
    raw_bytes = Path(wav_file).read_bytes()
    b64_audio = base64.b64encode(raw_bytes).decode("ascii")
    payload: dict[str, Any] = {
        "model": target_model,
        "input_audio": {
            "data": b64_audio,
            "format": "wav",
        },
    }
    norm_lang = _normalize_language(language)
    if norm_lang:
        payload["language"] = norm_lang
    if hint:
        payload["prompt"] = hint

    req = urllib.request.Request(
        _OPENROUTER_TRANSCRIPTIONS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {effective_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/TimInTech/blitztext-linux",
            "X-Title": "BlitztextLinux",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_CLOUD_REQUEST_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
            err_json = json.loads(err_body)
            if isinstance(err_json, dict) and isinstance(err_json.get("error"), dict):
                detail = str(err_json["error"].get("message") or "")
        except Exception:
            detail = ""
        msg = f"OpenRouter STT HTTP {exc.code}"
        if detail:
            msg = f"{msg}: {detail}"
        raise TranscribeError(msg) from exc

    data = json.loads(body)
    if not isinstance(data, dict):
        return ""
    if "error" in data:
        err = data["error"]
        err_msg = err.get("message") if isinstance(err, dict) else str(err)
        raise TranscribeError(f"OpenRouter STT Fehler: {err_msg}")
    text = data.get("text")
    return text.strip() if isinstance(text, str) else ""


def _transcribe_openai_cloud(
    wav_file: str,
    model_name: str,
    language: str,
    hint: str | None = None,
    api_key: str = "",
) -> str:
    effective_key = (
        api_key.strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
    )
    if not effective_key:
        raise TranscribeError(
            "OpenAI API-Key nicht gesetzt. Bitte OPENAI_API_KEY in "
            "~/.config/blitztext-linux/secrets.env setzen."
        )
    try:
        import openai  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError("openai-Paket nicht installiert. Bitte: pip install openai") from exc

    target_model = _resolve_openai_cloud_model(model_name)
    client = openai.OpenAI(api_key=effective_key, max_retries=1, timeout=_CLOUD_REQUEST_TIMEOUT)
    kwargs: dict[str, Any] = {"model": target_model}
    norm_lang = _normalize_language(language)
    if norm_lang:
        kwargs["language"] = norm_lang
    if hint:
        kwargs["prompt"] = hint

    with open(wav_file, "rb") as audio_file:
        response = client.audio.transcriptions.create(file=audio_file, **kwargs)
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text.strip()
    if isinstance(response, dict) and isinstance(response.get("text"), str):
        return response["text"].strip()
    return ""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) < 2:
        logger.error("Usage: transcribe.py <wav_file> [model] [language] [backend]")
        return 1

    wav_file = sys.argv[1]
    model_name = sys.argv[2] if len(sys.argv) > 2 else "base"
    language = sys.argv[3] if len(sys.argv) > 3 else "de"
    backend = sys.argv[4] if len(sys.argv) > 4 else "openai-whisper"

    if backend not in VALID_BACKENDS:
        logger.error("Invalid backend '%s'. Valid: %s", backend, sorted(VALID_BACKENDS))
        return 1
    if backend in {"openai-whisper", "faster-whisper"} and model_name not in VALID_MODEL_NAMES:
        logger.error("Invalid model name '%s'. Valid: %s", model_name, sorted(VALID_MODEL_NAMES))
        return 1
    if not os.path.isfile(wav_file):
        logger.error("WAV file not found: %s", wav_file)
        return 1
    if os.path.getsize(wav_file) <= _WAV_HEADER_BYTES:
        logger.error("WAV file contains no audio data")
        return 1

    try:
        text = transcribe(wav_file, model=model_name, language=language, backend=backend)
    except ImportError as exc:
        logger.error("Required dependency missing: %s", exc)
        return 1
    except Exception as exc:
        logger.error("Transcription failed: %s", exc)
        return 1

    if text:
        print(text, end="", flush=True)
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s: %(message)s",
    )
    raise SystemExit(main())

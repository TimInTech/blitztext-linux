#!/usr/bin/env python3
"""Transcribe a WAV file with Whisper.

Kopiert aus whisper-dictation app/transcribe.py v0.2.19.
Aenderungen gegenueber Original:
  - Logger-Name: blitztext.transcribe
  - Neue oeffentliche Funktion transcribe() fuer direkten Python-Import
    (BlitztextLinux ruft nicht per subprocess auf)
  - main() und CLI-Interface bleiben unveraendert erhalten

Supports both openai-whisper and faster-whisper backends.
"""
from __future__ import annotations

import logging
import os
import sys
import warnings
from pathlib import Path
from typing import Optional

logger = logging.getLogger("blitztext.transcribe")

VALID_MODEL_NAMES = {
    "tiny", "base", "small", "medium",
    "large", "large-v2", "large-v3", "large-v3-turbo",
}
VALID_BACKENDS = {"openai-whisper", "faster-whisper"}


class TranscribeError(Exception):
    """Raised when transcription fails (missing dep, bad file, model error)."""


# ---------------------------------------------------------------------------
# Public API (neu gegenueber whisper-dictation)
# ---------------------------------------------------------------------------

def transcribe(
    wav_file: Path | str,
    model: str = "base",
    language: str = "de",
    backend: str = "openai-whisper",
    custom_terms: list[str] | None = None,
) -> str:
    """Transkribiert eine WAV-Datei und gibt den Text zurueck.

    Args:
        wav_file: Pfad zur WAV-Datei (16 kHz, mono).
        model:    Whisper-Modellname (z. B. 'base', 'small').
        language: Sprachcode ('de', 'en', ...) oder 'auto' fuer Autodetect.
        backend:  'openai-whisper' | 'faster-whisper'
        custom_terms: Optionale Eigennamen/Fachbegriffe als Transkriptions-Hint.

    Returns:
        Transkribierter Text (stripped). Leer wenn nichts erkannt.

    Raises:
        TranscribeError: Bei fehlender Abhaengigkeit, fehlendem File oder
                         Modell-Fehler.
    """
    wav_file = Path(wav_file)

    if model not in VALID_MODEL_NAMES:
        raise TranscribeError(
            f"Ungültiger Modellname {model!r}. Gültig: {sorted(VALID_MODEL_NAMES)}"
        )
    if backend not in VALID_BACKENDS:
        raise TranscribeError(
            f"Ungültiger Backend {backend!r}. Gültig: {sorted(VALID_BACKENDS)}"
        )
    if not wav_file.is_file():
        raise TranscribeError(f"WAV-Datei nicht gefunden: {wav_file}")
    if wav_file.stat().st_size == 0:
        raise TranscribeError(f"WAV-Datei ist leer: {wav_file}")

    try:
        hint = _build_transcription_hint(custom_terms)
        hotwords = _build_hotwords(custom_terms)
        if backend == "faster-whisper":
            return _transcribe_faster(str(wav_file), model, language, hint=hint, hotwords=hotwords)
        return _transcribe_openai(str(wav_file), model, language, hint=hint)
    except ImportError as exc:
        raise TranscribeError(str(exc)) from exc
    except Exception as exc:
        raise TranscribeError(f"Transkription fehlgeschlagen: {exc}") from exc


# ---------------------------------------------------------------------------
# Backend-Implementierungen (unveraendert aus whisper-dictation)
# ---------------------------------------------------------------------------

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
    if _should_force_cpu_for_openai():
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
    whisper = _load_openai_whisper_module()

    model = whisper.load_model(model_name)
    result = model.transcribe(
        wav_file,
        language=_normalize_language(language),
        initial_prompt=hint,
    )
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

    model = WhisperModel(model_name, device="auto", compute_type="int8")
    segments, _ = model.transcribe(
        wav_file,
        language=_normalize_language(language),
        initial_prompt=hint,
        hotwords=hotwords,
    )
    parts = [getattr(seg, "text", "") for seg in segments]
    return " ".join(parts).strip()


# ---------------------------------------------------------------------------
# CLI (unveraendert aus whisper-dictation)
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) < 2:
        logger.error("Usage: transcribe.py <wav_file> [model] [language] [backend]")
        return 1

    wav_file = sys.argv[1]
    model_name = sys.argv[2] if len(sys.argv) > 2 else "base"
    language = sys.argv[3] if len(sys.argv) > 3 else "de"
    backend = sys.argv[4] if len(sys.argv) > 4 else "openai-whisper"

    if model_name not in VALID_MODEL_NAMES:
        logger.error("Invalid model name '%s'. Valid: %s", model_name, sorted(VALID_MODEL_NAMES))
        return 1
    if backend not in VALID_BACKENDS:
        logger.error("Invalid backend '%s'. Valid: %s", backend, sorted(VALID_BACKENDS))
        return 1
    if not os.path.isfile(wav_file):
        logger.error("WAV file not found: %s", wav_file)
        return 1
    if os.path.getsize(wav_file) == 0:
        logger.error("WAV file is empty")
        return 1

    try:
        if backend == "faster-whisper":
            text = _transcribe_faster(wav_file, model_name, language)
        else:
            text = _transcribe_openai(wav_file, model_name, language)
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

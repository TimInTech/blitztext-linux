from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app import transcribe as transcribe_module
from app.transcribe import TranscribeError, transcribe

WAV_WITH_SAMPLES = b"RIFF" + bytes(40) + b"data"


def test_transcribe_resolves_path_before_backend_call(tmp_path: Path):
    wav_file = tmp_path / "sample.wav"
    wav_file.write_bytes(WAV_WITH_SAMPLES)

    with patch("app.transcribe.Path.resolve", autospec=True, side_effect=lambda self: self) as resolve_mock, \
         patch("app.transcribe._transcribe_openai", return_value="OK") as backend_mock:
        result = transcribe(wav_file, backend="openai-whisper")

    assert result == "OK"
    resolve_mock.assert_called_once()
    backend_mock.assert_called_once()


def test_transcribe_openai_cpu_override_is_local_to_the_call(tmp_path: Path, monkeypatch):
    wav_file = tmp_path / "sample.wav"
    wav_file.write_bytes(WAV_WITH_SAMPLES)
    monkeypatch.delenv("WHISPER_USE_CUDA", raising=False)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "7")

    observed = {}

    class FakeModel:
        def transcribe(self, *_args, **_kwargs):
            observed["during_transcribe"] = os.environ.get("CUDA_VISIBLE_DEVICES")
            return {"text": " Hallo "}

    fake_model = FakeModel()

    class FakeWhisperModule:
        @staticmethod
        def load_model(_model_name):
            observed["during_load_model"] = os.environ.get("CUDA_VISIBLE_DEVICES")
            return fake_model

    with patch("app.transcribe._load_openai_whisper_module", return_value=FakeWhisperModule()):
        result = transcribe(wav_file, backend="openai-whisper")

    assert result == "Hallo"
    assert observed == {
        "during_load_model": "",
        "during_transcribe": "",
    }
    assert os.environ.get("CUDA_VISIBLE_DEVICES") == "7"


@pytest.mark.parametrize("content", [b"", b"RIFF" + bytes(40)])
def test_transcribe_rejects_wav_without_samples(tmp_path: Path, content: bytes):
    wav_file = tmp_path / "sample.wav"
    wav_file.write_bytes(content)

    with patch("app.transcribe._transcribe_openai") as backend_mock:
        with pytest.raises(TranscribeError):
            transcribe(wav_file, backend="openai-whisper")

    backend_mock.assert_not_called()


class _CountingWhisperModule:
    def __init__(self) -> None:
        self.loads: list[str] = []

    def load_model(self, model_name):
        self.loads.append(model_name)

        class _Model:
            def transcribe(self, *_args, **_kwargs):
                return {"text": "Hallo"}

        return _Model()


def test_model_is_cached_between_calls_and_reloaded_after_unload(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BLITZTEXT_MODEL_CACHE_SECONDS", "600")
    wav_file = tmp_path / "sample.wav"
    wav_file.write_bytes(WAV_WITH_SAMPLES)
    module = _CountingWhisperModule()

    with patch("app.transcribe._load_openai_whisper_module", return_value=module):
        transcribe(wav_file, model="base")
        transcribe(wav_file, model="base")
        assert module.loads == ["base"]

        transcribe(wav_file, model="small")
        assert module.loads == ["base", "small"]
        assert len(transcribe_module._model_cache) == 1

        transcribe_module.unload_cached_models()
        transcribe(wav_file, model="small")
        assert module.loads == ["base", "small", "small"]


def test_model_cache_disabled_reloads_every_call(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("BLITZTEXT_MODEL_CACHE_SECONDS", "0")
    wav_file = tmp_path / "sample.wav"
    wav_file.write_bytes(WAV_WITH_SAMPLES)
    module = _CountingWhisperModule()

    with patch("app.transcribe._load_openai_whisper_module", return_value=module):
        transcribe(wav_file, model="base")
        transcribe(wav_file, model="base")

    assert module.loads == ["base", "base"]
    assert transcribe_module._model_cache == {}


def _write_pcm_wav(path: Path, seconds: float) -> None:
    import wave

    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(bytes(int(16000 * seconds) * 2))


@pytest.mark.parametrize(("seconds", "expect_hint"), [(0.5, False), (1.5, True)])
def test_vocabulary_hint_only_for_recordings_of_at_least_0_9s(tmp_path: Path, seconds, expect_hint):
    wav_file = tmp_path / "sample.wav"
    _write_pcm_wav(wav_file, seconds)

    with patch("app.transcribe._transcribe_openai", return_value="OK") as backend_mock:
        transcribe(wav_file, backend="openai-whisper", custom_terms=["Blitztext"])

    hint = backend_mock.call_args.kwargs["hint"]
    assert (hint is not None) is expect_hint


def test_transcribe_openrouter_sends_base64_wav_and_prompt(tmp_path: Path, monkeypatch):
    import json

    wav_file = tmp_path / "sample.wav"
    _write_pcm_wav(wav_file, 1.5)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")

    captured = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"text": " Hallo von OpenRouter "}).encode("utf-8")

    def _fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["auth"] = req.get_header("Authorization")
        captured["payload"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse()

    with patch("app.transcribe.urllib.request.urlopen", side_effect=_fake_urlopen):
        result = transcribe(
            wav_file,
            model="base",
            language="de",
            backend="openrouter",
            custom_terms=["Blitztext"],
        )

    assert result == "Hallo von OpenRouter"
    assert captured["url"] == "https://openrouter.ai/api/v1/audio/transcriptions"
    assert captured["auth"] == "Bearer test-or-key"
    assert captured["payload"]["model"] == "openai/gpt-4o-transcribe"
    assert captured["payload"]["language"] == "de"
    assert captured["payload"]["input_audio"]["format"] == "wav"
    assert captured["payload"]["prompt"] == "Eigennamen und Begriffe: Blitztext"


def test_transcribe_openrouter_raises_without_api_key(tmp_path: Path, monkeypatch):
    wav_file = tmp_path / "sample.wav"
    _write_pcm_wav(wav_file, 1.0)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(TranscribeError, match="OpenRouter API-Key"):
        transcribe(wav_file, backend="openrouter", api_key="")


def test_transcribe_openai_cloud_uses_client_and_maps_model(tmp_path: Path, monkeypatch):
    import sys
    import types
    from unittest.mock import MagicMock

    wav_file = tmp_path / "sample.wav"
    _write_pcm_wav(wav_file, 1.5)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    client = MagicMock()
    client.audio.transcriptions.create.return_value = types.SimpleNamespace(text=" Hallo Cloud ")
    fake_openai = types.SimpleNamespace(OpenAI=MagicMock(return_value=client))
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    result = transcribe(wav_file, model="base", language="de", backend="openai-cloud", api_key="test-oa-key")

    assert result == "Hallo Cloud"
    assert fake_openai.OpenAI.call_args.kwargs["api_key"] == "test-oa-key"
    kwargs = client.audio.transcriptions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-transcribe"
    assert kwargs["language"] == "de"


def test_transcribe_openai_cloud_raises_without_api_key(tmp_path: Path, monkeypatch):
    wav_file = tmp_path / "sample.wav"
    _write_pcm_wav(wav_file, 1.0)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(TranscribeError, match="OpenAI API-Key"):
        transcribe(wav_file, backend="openai-cloud", api_key="")


def test_transcribe_cloud_backend_accepts_custom_model_id():
    assert transcribe_module._resolve_openrouter_model("whisper-1") == "openai/whisper-1"
    assert transcribe_module._resolve_openrouter_model("vendor/model") == "vendor/model"
    assert transcribe_module._resolve_openai_cloud_model("openai/whisper-1") == "whisper-1"

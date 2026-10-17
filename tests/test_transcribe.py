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

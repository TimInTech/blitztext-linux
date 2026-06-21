from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from app.transcribe import transcribe


def test_transcribe_resolves_path_before_backend_call(tmp_path: Path):
    wav_file = tmp_path / "sample.wav"
    wav_file.write_bytes(b"RIFFdata")

    with patch("app.transcribe.Path.resolve", autospec=True, side_effect=lambda self: self) as resolve_mock, \
         patch("app.transcribe._transcribe_openai", return_value="OK") as backend_mock:
        result = transcribe(wav_file, backend="openai-whisper")

    assert result == "OK"
    resolve_mock.assert_called_once()
    backend_mock.assert_called_once()


def test_transcribe_openai_cpu_override_is_local_to_the_call(tmp_path: Path, monkeypatch):
    wav_file = tmp_path / "sample.wav"
    wav_file.write_bytes(b"RIFFdata")
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

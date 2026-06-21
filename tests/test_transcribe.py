from __future__ import annotations

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

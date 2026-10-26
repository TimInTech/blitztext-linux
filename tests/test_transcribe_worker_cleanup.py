"""The transcribe worker cleans the raw transcript locally before pasting or rewriting."""
from unittest.mock import MagicMock, patch

from app.blitztext_linux import _TranscribeWorker
from app.workflows import WorkflowType


def _run(tmp_path, raw, **kwargs):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    paste = MagicMock()
    worker = _TranscribeWorker(
        wav_file=wav, model="base", language="de", backend="openai-whisper",
        workflow=WorkflowType.TRANSCRIPTION, llm_service=MagicMock(), autopaste=False,
        paste_service=paste, **kwargs,
    )
    worker.signals = MagicMock()
    with patch("app.blitztext_linux.transcribe", return_value=raw):
        worker.run()
    return worker, paste


def test_custom_terms_and_fillers_are_cleaned_before_paste(tmp_path):
    _, paste = _run(tmp_path, "äh mit Blitz Text Linux", custom_terms=["Blitztext"])
    paste.clipboard_only.assert_called_once_with("mit Blitztext Linux")


def test_replacements_are_applied(tmp_path):
    _, paste = _run(tmp_path, "ich nutze n acht n", replacements=[{"spoken": "n acht n", "written": "n8n"}])
    paste.clipboard_only.assert_called_once_with("ich nutze n8n")


def test_cleanup_feeds_the_llm_workflow(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    llm = MagicMock()
    llm.rewrite.return_value = "ok"
    worker = _TranscribeWorker(
        wav_file=wav, model="base", language="de", backend="openai-whisper",
        workflow=WorkflowType.TEXT_IMPROVER, llm_service=llm, autopaste=False,
        paste_service=MagicMock(), custom_terms=["Blitztext"],
    )
    worker.signals = MagicMock()
    with patch("app.blitztext_linux.transcribe", return_value="mit Blitz Text"):
        worker.run()
    llm.rewrite.assert_called_once_with(WorkflowType.TEXT_IMPROVER, "mit Blitztext")


def test_only_fillers_means_no_speech(tmp_path):
    worker, paste = _run(tmp_path, "äh ähm")
    worker.signals.no_speech.emit.assert_called_once()
    paste.clipboard_only.assert_not_called()


def _run_ai(tmp_path, **kwargs):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    llm, paste = MagicMock(), MagicMock()
    worker = _TranscribeWorker(
        wav_file=wav, model="base", language="de", backend="openai-whisper",
        workflow=WorkflowType.TEXT_IMPROVER, llm_service=llm, autopaste=False,
        paste_service=paste, **kwargs,
    )
    worker.signals = MagicMock()
    with patch("app.blitztext_linux.transcribe", return_value="hallo welt"):
        worker.run()
    return worker, llm, paste


def test_skip_llm_pastes_the_raw_text_when_the_compose_window_is_gone(tmp_path):
    worker, llm, paste = _run_ai(tmp_path, route_to_compose=False, skip_llm=True)
    llm.rewrite.assert_not_called()
    paste.clipboard_only.assert_called_once_with("hallo welt")
    worker.signals.error.emit.assert_not_called()


def test_compose_routing_still_skips_llm_and_paste(tmp_path):
    _, llm, paste = _run_ai(tmp_path, route_to_compose=True)
    llm.rewrite.assert_not_called()
    paste.clipboard_only.assert_not_called()
    paste.paste.assert_not_called()


def test_worker_passes_transcription_api_key_to_transcribe(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    worker = _TranscribeWorker(
        wav_file=wav, model="base", language="de", backend="openrouter",
        workflow=WorkflowType.TRANSCRIPTION, llm_service=MagicMock(), autopaste=False,
        paste_service=MagicMock(), transcription_api_key="test-key",
    )
    worker.signals = MagicMock()
    with patch("app.blitztext_linux.transcribe", return_value="Hallo") as mock_transcribe:
        worker.run()
    assert mock_transcribe.call_args.kwargs["api_key"] == "test-key"
    assert mock_transcribe.call_args.kwargs["backend"] == "openrouter"

"""GUI Local recordings must not use configured cloud STT, even after hotkeys."""
import os
from unittest.mock import Mock

import pytest

from app.workflows import WorkflowType

pytestmark = pytest.mark.skipif(
    os.environ.get("WHISPER_GUI_TESTS") != "1", reason="requires WHISPER_GUI_TESTS=1"
)


@pytest.fixture
def cloud_pipeline(tmp_path, monkeypatch):
    from PyQt6.QtCore import QThreadPool
    from PyQt6.QtWidgets import QApplication
    from app import blitztext_linux as main
    from app.config import Config

    qapp = QApplication.instance() or QApplication([])
    config = Config.load(tmp_path / "config.json")
    config.notes_folder = ""
    config.autopaste = False
    monkeypatch.setattr(main.Config, "load", lambda *a, **kw: config)
    monkeypatch.setattr(main.BlitztextApp, "start_hotkey_worker", lambda self: None)
    app = main.BlitztextApp(qapp)
    app.audio_recorder = Mock()
    wav = tmp_path / "recording.wav"
    wav.write_bytes(b"RIFF")
    app.audio_recorder.stop.return_value = wav
    app.llm_service = Mock()
    app.llm_service.is_available.return_value = True
    app.llm_service.rewrite.return_value = "Rewritten text"
    app.paste_service = Mock()
    monkeypatch.setattr(app, "_on_worker_result", lambda *a, **kw: None)
    monkeypatch.setattr(app, "_compose_voice_routing_enabled", lambda: False)
    monkeypatch.setattr(main.AudioRecorder, "cleanup_recording", lambda path: None)
    workers = []
    monkeypatch.setattr(QThreadPool.globalInstance(), "start", workers.append)
    # Observe the actual transcription boundary without audio, model, or network I/O.
    calls = []
    def transcribe(**kwargs):
        calls.append(kwargs)
        return "Private dictation"
    monkeypatch.setattr(main, "transcribe", transcribe)
    key_lookups = []
    def resolve_key():
        key_lookups.append(True)
        return "test-stt-key"
    monkeypatch.setattr(config, "resolve_transcription_api_key", resolve_key)
    yield app, workers, calls, key_lookups
    app.stop_hotkey_worker()
    if app._main_window is not None:
        app._main_window.close()


def _finish(app, workers):
    app.gui_toggle_recording(WorkflowType.LOCAL)
    assert len(workers) == 1
    workers[0].run()


@pytest.mark.parametrize("backend", ["openai-cloud", "openrouter"])
@pytest.mark.parametrize("entry", ["initial", "ai_to_local", "after_cloud_hotkey", "local_click_after_cloud_hotkey", "missing_selection"])
def test_gui_local_never_sends_audio_or_key_to_cloud(cloud_pipeline, backend, entry):
    app, workers, calls, key_lookups = cloud_pipeline
    app.config.backend = backend
    window = app._ensure_main_window()
    if entry == "ai_to_local":
        window._seg_ai.click()
        window._seg_local.click()
    elif entry in {"after_cloud_hotkey", "local_click_after_cloud_hotkey"}:
        window.update_state("IDLE", WorkflowType.TRANSCRIPTION, None)
        if entry == "local_click_after_cloud_hotkey":
            window._seg_local.click()
    elif entry == "missing_selection":
        window._workflow_combo.setCurrentIndex(-1)
    window._btn_toggle.click()
    _finish(app, workers)
    assert len(calls) == 1
    assert calls[0]["backend"] == "faster-whisper"
    assert calls[0]["api_key"] == ""
    assert key_lookups == []
    app.llm_service.rewrite.assert_not_called()


@pytest.mark.parametrize("backend", ["openai-cloud", "openrouter"])
@pytest.mark.parametrize("workflow", [WorkflowType.TRANSCRIPTION, WorkflowType.LOCAL, WorkflowType.TEXT_IMPROVER])
def test_explicit_hotkey_workflows_keep_their_backend_semantics(cloud_pipeline, backend, workflow):
    app, workers, calls, key_lookups = cloud_pipeline
    app.config.backend = backend
    app._on_workflow_triggered(workflow)
    # A GUI stop must not reinterpret a recording started by an explicit hotkey.
    _finish(app, workers)
    assert len(calls) == 1
    if workflow == WorkflowType.LOCAL:
        assert calls[0]["backend"] == "faster-whisper"
        assert calls[0]["api_key"] == ""
        assert key_lookups == []
    else:
        assert calls[0]["backend"] == backend
        assert calls[0]["api_key"] == "test-stt-key"
        assert len(key_lookups) == 1
    assert app.llm_service.rewrite.called == (workflow == WorkflowType.TEXT_IMPROVER)

"""Discard uses the real controller handlers without starting a transcription pipeline."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.blitztext_linux import BlitztextApp
from app.workflows import WorkflowType


@pytest.fixture
def controller(monkeypatch):
    recorder = Mock()
    recorder.is_recording.return_value = False
    app = SimpleNamespace(
        state="RECORDING", current_workflow=WorkflowType.TRANSCRIPTION,
        _recording_routes_to_compose=True,
        config=SimpleNamespace(hotkey_mode="hold"),
        audio_recorder=recorder, show_tray_error=Mock(),
    )
    app._set_state = lambda state, reason: setattr(app, "state", state)
    # Keep the real processing path so an accidental call cannot be swallowed.
    app._stop_recording_and_process = lambda: BlitztextApp._stop_recording_and_process(app)
    worker = Mock(side_effect=AssertionError("discard must not create a transcription worker"))
    monkeypatch.setattr("app.blitztext_linux._TranscribeWorker", worker)
    return app, worker


@pytest.mark.parametrize("mode", ["hold", "toggle"])
def test_discard_and_delayed_release_never_transcribe(controller, mode):
    app, worker = controller
    app.config.hotkey_mode = mode
    BlitztextApp.gui_discard(app)
    BlitztextApp._on_recording_stop(app)
    BlitztextApp.gui_discard(app)

    assert app.state == "IDLE"
    assert app.current_workflow is None
    assert not app._recording_routes_to_compose
    app.audio_recorder.discard.assert_called_once()
    app.audio_recorder.stop.assert_not_called()
    worker.assert_not_called()
    app.show_tray_error.assert_not_called()


def test_failed_discard_retains_recording_and_can_be_retried(controller):
    app, worker = controller
    app.audio_recorder.is_recording.return_value = True
    BlitztextApp.gui_discard(app)

    assert app.state == "RECORDING"
    assert app.current_workflow == WorkflowType.TRANSCRIPTION
    assert app._recording_routes_to_compose
    app.show_tray_error.assert_called_once()
    app.audio_recorder.stop.assert_not_called()
    worker.assert_not_called()

    app.audio_recorder.is_recording.return_value = False
    BlitztextApp.gui_discard(app)
    assert app.state == "IDLE"
    assert app.current_workflow is None
    assert not app._recording_routes_to_compose
    assert app.audio_recorder.discard.call_count == 2

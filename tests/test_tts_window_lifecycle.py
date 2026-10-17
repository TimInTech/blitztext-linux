"""Lifecycle tests for TtsWindow: closing via done() and late thread signals."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from app.config import Config
from app import tts_window


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _SlowService:
    api_key = "sk-test-not-a-real-key"

    def __init__(self, delay: float) -> None:
        self._delay = delay

    def is_available(self) -> bool:
        return True

    def synthesize(self, text: str, output_path=None) -> str:
        time.sleep(self._delay)
        return output_path


@pytest.fixture
def cloud_window(qapp, tmp_path, monkeypatch):
    cfg = Config.load(tmp_path / "config.json")
    cfg.tts_provider = "openai"
    cfg.tts_openai_consent = True
    monkeypatch.setattr(cfg, "save", lambda: None)
    monkeypatch.setattr(tts_window, "TTS_RUNTIME_DIR", str(tmp_path))
    service = _SlowService(delay=0.3)
    monkeypatch.setattr(tts_window, "CloudTtsService", lambda _config: service)
    window = tts_window.TtsWindow(cfg)
    window.set_text("Hallo Welt")
    yield window
    thread = window._cloud_thread
    if thread is not None:
        thread.wait(3000)
    for thread in list(window._detached_cloud_threads):
        thread.wait(3000)
    qapp.processEvents()
    window.close()
    qapp.processEvents()


@pytest.mark.parametrize("close_via", ["accept", "reject"])
def test_done_shuts_down_playback_before_owner_releases_dialog(qapp, tmp_path, close_via):
    cfg = Config.load(tmp_path / "config.json")
    window = tts_window.TtsWindow(cfg)
    window.show()
    with patch.object(tts_window.TtsWindow, "_shutdown_playback") as shutdown:
        getattr(window, close_via)()
    shutdown.assert_called_once_with()
    window.close()
    qapp.processEvents()


def test_late_finished_of_cancelled_thread_keeps_new_cloud_job(qapp, cloud_window):
    cloud_window._on_speak_clicked()
    old_thread = cloud_window._cloud_thread
    assert old_thread is not None

    # Replay while the first request is still running: the old thread finishes
    # during the detach wait, its 'finished' signal is delivered afterwards.
    cloud_window._on_replay_clicked()
    new_thread = cloud_window._cloud_thread
    assert new_thread is not None and new_thread is not old_thread

    qapp.processEvents()

    assert cloud_window._cloud_thread is new_thread
    assert cloud_window._is_speaking() is True

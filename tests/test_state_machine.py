"""Tests für State-Reset und Hotkey-Event-Handling (Bug v0.2.20).

Deckt die eigentliche Root Cause des "Icon bleibt orange / zweiter Toggle tot"
Bugs ab: ein blockierender Paste-Subprocess ohne Timeout liess den
Transkriptions-Worker nie zurueckkehren, sodass der App-State dauerhaft auf
TRANSCRIBING/LLM_REWRITING haengen blieb.

GUI-Tests (echte BlitztextApp-Statemaschine) laufen nur mit WHISPER_GUI_TESTS=1,
da sie QApplication + Tray-Icon (Display) benoetigen.
"""
import logging
import os
import subprocess
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from app.paste_service import PasteService, PasteServiceError
from app.hotkey_service import HotkeyWorker
from app.workflows import WorkflowType


# ---------------------------------------------------------------------------
# Phase 1: Paste-Subprocess-Timeouts (eigentliche Root Cause)
# ---------------------------------------------------------------------------

class TestPasteTimeouts:
    def test_paste_ydotool_timeout_does_not_hang(self):
        """ydotool-Timeout darf NICHT propagieren -- der Worker muss
        zurueckkehren, damit der State auf IDLE faellt. Clipboard ist gesetzt."""
        svc = PasteService(autopaste=True)
        with patch("app.paste_service.shutil.which", return_value="/usr/bin/tool"), \
             patch("app.paste_service.time.sleep"), \
             patch("app.paste_service.subprocess.run") as run_mock:
            def side_effect(cmd, *args, **kwargs):
                if cmd[0] == "wl-copy":
                    return subprocess.CompletedProcess(cmd, 0, b"", b"")
                raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 5))
            run_mock.side_effect = side_effect
            # Darf nicht werfen und nicht haengen
            svc.paste("hallo welt")

    def test_paste_wl_copy_timeout_raises_pasteerror(self):
        """wl-copy-Timeout wird als PasteServiceError signalisiert -> Worker
        emittiert 'error' -> State faellt auf IDLE."""
        svc = PasteService(autopaste=True)
        with patch("app.paste_service.shutil.which", return_value="/usr/bin/wl-copy"), \
             patch("app.paste_service.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(["wl-copy"], 5)):
            with pytest.raises(PasteServiceError):
                svc.paste("hallo welt")

    def test_paste_passes_timeout_to_subprocess(self):
        svc = PasteService(autopaste=False)
        with patch("app.paste_service.shutil.which", return_value="/usr/bin/wl-copy"), \
             patch("app.paste_service.subprocess.run",
                   return_value=subprocess.CompletedProcess(["wl-copy"], 0, b"", b"")) as run_mock:
            svc.paste("text")
        assert run_mock.call_args.kwargs.get("timeout") is not None

    def test_paste_uses_configured_key_delay_for_ydotool(self):
        svc = PasteService(autopaste=True, key_delay_ms=135)
        with patch("app.paste_service.shutil.which", return_value="/usr/bin/tool"), \
             patch("app.paste_service._is_terminal_active", return_value=False), \
             patch.object(PasteService, "_cleanup_copyq"), \
             patch("app.paste_service.time.sleep"), \
             patch("app.paste_service.subprocess.run") as run_mock:
            def side_effect(cmd, *args, **kwargs):
                if cmd[0] == "wl-copy":
                    return subprocess.CompletedProcess(cmd, 0, b"", b"")
                return subprocess.CompletedProcess(cmd, 0, b"", b"")
            run_mock.side_effect = side_effect
            svc.paste("hallo welt")

        ydotool_call = run_mock.call_args_list[1]
        assert ydotool_call.args[0][:4] == ["ydotool", "key", "--key-delay", "135"]

    def test_paste_missing_ydotoold_does_not_raise(self, caplog):
        svc = PasteService(autopaste=True)
        caplog.set_level(logging.WARNING, logger="blitztext.paste_service")
        with patch("app.paste_service.shutil.which", return_value="/usr/bin/tool"), \
             patch("app.paste_service.time.sleep"), \
             patch("app.paste_service.subprocess.run") as run_mock:
            def side_effect(cmd, *args, **kwargs):
                if cmd[0] == "wl-copy":
                    return subprocess.CompletedProcess(cmd, 0, b"", b"")
                return subprocess.CompletedProcess(
                    cmd,
                    1,
                    b"",
                    b"failed to connect to /run/user/1000/.ydotool_socket: No such file or directory",
                )
            run_mock.side_effect = side_effect

            svc.paste("hallo welt")

        assert "ydotoold nicht verfügbar" in caplog.text

    def test_force_autopaste_override_enables_ydotool(self):
        """force_autopaste=True überschreibt autopaste=False: Clipboard + ydotool."""
        svc = PasteService(autopaste=False)
        with patch("app.paste_service.shutil.which", return_value="/usr/bin/tool"), \
             patch("app.paste_service._is_terminal_active", return_value=False), \
             patch.object(PasteService, "_cleanup_copyq"), \
             patch.object(PasteService, "_read_clipboard", return_value="alter text"), \
             patch("app.paste_service.time.sleep"), \
             patch("app.paste_service.subprocess.run") as run_mock:
            def side_effect(cmd, *args, **kwargs):
                return subprocess.CompletedProcess(cmd, 0, b"", b"")
            run_mock.side_effect = side_effect
            svc.paste("hallo welt", force_autopaste=True)
        assert run_mock.call_count == 3
        cmd_names = [call.args[0][0] for call in run_mock.call_args_list]
        assert any(name in ("wl-copy", "xclip") for name in cmd_names)
        assert "ydotool" in cmd_names

    def test_autopaste_false_without_override_skips_ydotool(self):
        """autopaste=False ohne force_autopaste: nur Clipboard-Write, kein ydotool."""
        svc = PasteService(autopaste=False)
        with patch("app.paste_service.shutil.which", return_value="/usr/bin/tool"), \
             patch.object(PasteService, "_cleanup_copyq"), \
             patch("app.paste_service.subprocess.run") as run_mock:
            run_mock.return_value = subprocess.CompletedProcess([], 0, b"", b"")
            svc.paste("hallo welt")
        assert run_mock.call_count == 1
        cmd_names = [call.args[0][0] for call in run_mock.call_args_list]
        assert "ydotool" not in cmd_names


# ---------------------------------------------------------------------------
# Hilfen: minimales Fake-evdev fuer den HotkeyWorker-Event-Loop
# ---------------------------------------------------------------------------

_KEYCODES = {
    "EV_KEY": 1,
    "KEY_LEFTALT": 56, "KEY_RIGHTALT": 100,
    "KEY_LEFTCTRL": 29, "KEY_RIGHTCTRL": 97,
    "KEY_LEFTMETA": 125, "KEY_RIGHTMETA": 126,
    "KEY_LEFTSHIFT": 42, "KEY_RIGHTSHIFT": 54,
    "KEY_H": 35, "KEY_T": 20, "KEY_D": 32, "KEY_E": 18,
}


def _make_fake_ecodes():
    ec = types.SimpleNamespace(**_KEYCODES)
    # _key_name() greift auf ecodes.KEY zu
    ec.KEY = {code: name for name, code in _KEYCODES.items() if name != "EV_KEY"}
    return ec


class _FakeEvent:
    def __init__(self, code, value, etype):
        self.type = etype
        self.code = code
        self.value = value


class _FakeDevice:
    def __init__(self, worker, batch, ec):
        self.fd = 4242
        self.path = "/dev/input/event-fake"
        self._worker = worker
        self._batch = batch
        self._ec = ec
        self._read_done = False

    def capabilities(self):
        return {self._ec.EV_KEY: list(self._ec.KEY.keys())}

    def read(self):
        # Nach dem ersten Batch den Loop beenden
        self._worker._running = False
        if self._read_done:
            return []
        self._read_done = True
        return list(self._batch)

    def close(self):
        pass


def _run_worker_with_events(events, transcription_key="KEY_LEFTALT"):
    """Startet HotkeyWorker.run() mit injiziertem Fake-evdev und einem
    einzigen Event-Batch. Gibt die Liste ausgeloester WorkflowTypes zurueck."""
    ec = _make_fake_ecodes()
    worker = HotkeyWorker(hotkey_mode="toggle", transcription_key=transcription_key)

    triggered = []
    worker.workflow_triggered.connect(lambda wf: triggered.append(wf))

    fake_dev_holder = {}

    def fake_input_device(path):
        dev = _FakeDevice(worker, [], ec)
        fake_dev_holder["dev"] = dev
        return dev

    fake_evdev = types.ModuleType("evdev")
    fake_evdev.ecodes = ec
    fake_evdev.list_devices = lambda: ["/dev/input/event-fake"]
    fake_evdev.InputDevice = fake_input_device

    batch = [_FakeEvent(code, value, ec.EV_KEY) for (code, value) in events]

    def fake_select(rlist, wlist, xlist, timeout):
        # Batch jetzt in das aktive Device legen
        dev = fake_dev_holder.get("dev")
        if dev is not None:
            dev._batch = batch
        return (list(rlist), [], [])

    with patch.dict(sys.modules, {"evdev": fake_evdev}), \
         patch("select.select", side_effect=fake_select):
        worker.run()

    return triggered


# ---------------------------------------------------------------------------
# Phase 3: evdev value-Handling (KEY_LEFTALT)
# ---------------------------------------------------------------------------

class TestLeftAltEvents:
    def test_leftalt_keydown_triggers_toggle(self):
        """value=1 (key-down) loest die Transkription aus."""
        triggered = _run_worker_with_events([(_KEYCODES["KEY_LEFTALT"], 1)])
        assert triggered == [WorkflowType.TRANSCRIPTION]

    def test_leftalt_repeat_events_ignored(self):
        """value=2 (auto-repeat) darf KEINEN Toggle ausloesen."""
        triggered = _run_worker_with_events([(_KEYCODES["KEY_LEFTALT"], 2)])
        assert triggered == []

    def test_leftalt_keyup_does_not_trigger_in_toggle(self):
        """value=0 (key-up) loest im Toggle-Modus nichts aus."""
        triggered = _run_worker_with_events([(_KEYCODES["KEY_LEFTALT"], 0)])
        assert triggered == []


# ---------------------------------------------------------------------------
# Phase 2/3: BlitztextApp-Statemaschine (GUI-gated)
# ---------------------------------------------------------------------------

_GUI = os.environ.get("WHISPER_GUI_TESTS") == "1"
gui_only = pytest.mark.skipif(not _GUI, reason="benötigt WHISPER_GUI_TESTS=1 (Display)")


@pytest.fixture
def gui_app():
    from PyQt6.QtWidgets import QApplication
    from app.blitztext_linux import BlitztextApp
    qapp = QApplication.instance() or QApplication([])
    app = BlitztextApp(qapp)
    app.stop_hotkey_worker()  # kein echter evdev-Thread im Test
    yield app


@gui_only
class TestStateMachine:
    def test_state_returns_to_idle_after_result(self, gui_app):
        gui_app.state = "LLM_REWRITING"
        gui_app.current_workflow = WorkflowType.TEXT_IMPROVER
        gui_app._on_worker_result("fertiger text")
        assert gui_app.state == "IDLE"
        assert gui_app.current_workflow is None

    def test_state_returns_to_idle_after_error(self, gui_app):
        gui_app.state = "TRANSCRIBING"
        gui_app.current_workflow = WorkflowType.TRANSCRIPTION
        gui_app._on_worker_error("boom")
        assert gui_app.state == "IDLE"
        assert gui_app.current_workflow is None

    def test_orange_clears_after_result(self, gui_app):
        """Nach result darf der State nicht mehr auf einem Orange-Zustand stehen."""
        gui_app.state = "TRANSCRIBING"
        gui_app._on_worker_result("text")
        assert gui_app.state not in ("TRANSCRIBING", "LLM_REWRITING")
        assert gui_app._tray_error_message is None

    def test_second_toggle_possible_after_result(self, gui_app):
        """Nach einem vollstaendigen Zyklus muss ein neuer Toggle eine
        Aufnahme starten (State == IDLE -> RECORDING)."""
        gui_app.state = "LLM_REWRITING"
        gui_app._on_worker_result("text")
        assert gui_app.state == "IDLE"
        with patch.object(gui_app.audio_recorder, "start") as start_mock:
            gui_app._on_workflow_triggered(WorkflowType.TRANSCRIPTION)
            start_mock.assert_called_once()
        assert gui_app.state == "RECORDING"


@gui_only
class TestMainWindowControl:
    def test_gui_toggle_starts_and_stops(self, gui_app):
        """Maus-Klick startet im IDLE eine Aufnahme und stoppt sie im RECORDING,
        unabhaengig vom Hotkey-Modus."""
        with patch.object(gui_app.audio_recorder, "start") as start_mock:
            gui_app.gui_toggle_recording(WorkflowType.TRANSCRIPTION)
            start_mock.assert_called_once()
        assert gui_app.state == "RECORDING"

        from pathlib import Path
        with patch.object(gui_app.audio_recorder, "stop", return_value=Path("/tmp/x.wav")):
            gui_app.gui_toggle_recording(WorkflowType.TRANSCRIPTION)
        assert gui_app.state == "TRANSCRIBING"

    def test_gui_toggle_ignored_while_busy(self, gui_app):
        gui_app.state = "TRANSCRIBING"
        with patch.object(gui_app.audio_recorder, "start") as start_mock:
            gui_app.gui_toggle_recording(WorkflowType.TRANSCRIPTION)
            start_mock.assert_not_called()
        assert gui_app.state == "TRANSCRIBING"

    def test_gui_discard_returns_to_idle(self, gui_app):
        with patch.object(gui_app.audio_recorder, "start"):
            gui_app.gui_toggle_recording(WorkflowType.TRANSCRIPTION)
        assert gui_app.state == "RECORDING"
        with patch.object(gui_app.audio_recorder, "discard") as discard_mock:
            gui_app.gui_discard()
            discard_mock.assert_called_once()
        assert gui_app.state == "IDLE"

    def test_main_window_reflects_state(self, gui_app):
        win = gui_app._ensure_main_window()
        gui_app._set_state("RECORDING", "test")
        assert win._btn_toggle.text() == "Stopp"
        gui_app._set_state("IDLE", "test")
        assert win._btn_toggle.text() == "Start"

    def test_dictation_mode_syncs_window_and_tray(self, gui_app):
        win = gui_app._ensure_main_window()
        gui_app.set_dictation_mode(True)
        assert gui_app._dictation_mode is True
        assert gui_app.action_dictation.isChecked() is True
        assert win._btn_dictation.isChecked() is True
        gui_app.set_dictation_mode(False)
        assert win._btn_dictation.isChecked() is False

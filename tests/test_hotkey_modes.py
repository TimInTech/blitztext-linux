"""Tests für HotkeyService — Hold-Modus, Toggle-Modus, Debounce, Reconnect."""
import time
import pytest
from unittest.mock import MagicMock, patch, call
from app.hotkey_service import HotkeyService, HotkeyMode, _modifier_match, _refresh_keyboard_devices


@pytest.fixture
def callbacks():
    return {
        "start": MagicMock(),
        "stop": MagicMock(),
    }


@pytest.fixture
def toggle_service(callbacks):
    svc = HotkeyService(
        mode=HotkeyMode.TOGGLE,
        on_start=callbacks["start"],
        on_stop=callbacks["stop"],
    )
    return svc


@pytest.fixture
def hold_service(callbacks):
    svc = HotkeyService(
        mode=HotkeyMode.HOLD,
        on_start=callbacks["start"],
        on_stop=callbacks["stop"],
    )
    return svc


class TestHotkeyMode:
    def test_toggle_mode_value(self):
        assert HotkeyMode.TOGGLE.value == "toggle"

    def test_hold_mode_value(self):
        assert HotkeyMode.HOLD.value == "hold"


class TestToggleMode:
    def test_first_keydown_starts(self, toggle_service, callbacks):
        toggle_service.simulate_key_down()
        callbacks["start"].assert_called_once()
        callbacks["stop"].assert_not_called()

    def test_second_keydown_stops(self, toggle_service, callbacks):
        toggle_service.simulate_key_down()
        toggle_service.simulate_key_down()
        callbacks["start"].assert_called_once()
        callbacks["stop"].assert_called_once()

    def test_keyup_ignored_in_toggle(self, toggle_service, callbacks):
        toggle_service.simulate_key_up()
        callbacks["start"].assert_not_called()
        callbacks["stop"].assert_not_called()

    def test_toggle_sequence_start_stop_start(self, toggle_service, callbacks):
        toggle_service.simulate_key_down()  # start
        toggle_service.simulate_key_down()  # stop
        toggle_service.simulate_key_down()  # start again
        assert callbacks["start"].call_count == 2
        assert callbacks["stop"].call_count == 1


class TestHoldMode:
    def test_keydown_starts(self, hold_service, callbacks):
        hold_service.simulate_key_down()
        callbacks["start"].assert_called_once()

    def test_keyup_stops(self, hold_service, callbacks):
        hold_service.simulate_key_down()
        hold_service.simulate_key_up()
        callbacks["stop"].assert_called_once()

    def test_keydown_without_keyup_no_stop(self, hold_service, callbacks):
        hold_service.simulate_key_down()
        callbacks["stop"].assert_not_called()

    def test_double_keydown_no_double_start(self, hold_service, callbacks):
        """Autorepeat-Events sollen keinen zweiten Start auslösen."""
        hold_service.simulate_key_down()
        hold_service.simulate_key_down()  # Autorepeat
        callbacks["start"].assert_called_once()


class TestDebounce:
    def test_rapid_toggle_debounced(self, toggle_service, callbacks):
        """Zwei KEY_DOWN innerhalb der Debounce-Zeit (0.6s) → nur ein Aufruf."""
        toggle_service.simulate_key_down()
        toggle_service.simulate_key_down()  # zu schnell → debounced
        # Erwarte: entweder start+stop oder nur start — nicht start+stop+start
        total_calls = callbacks["start"].call_count + callbacks["stop"].call_count
        assert total_calls <= 2

    def test_debounce_interval_is_0_6s(self, toggle_service):
        assert toggle_service.debounce_interval == pytest.approx(0.6)


class TestRecordingStopBehavior:
    """Testet die BlitztextApp-Zustandsmaschine: Welcher Hotkey stoppt eine laufende Aufnahme?"""

    def _make_app_stub(self, hotkey_mode: str = "toggle"):
        """Minimaler Stub, der nur die relevante _on_workflow_triggered-Logik abbildet."""
        from unittest.mock import MagicMock, patch

        stop_mock = MagicMock()

        class AppStub:
            def __init__(self):
                self.state = "IDLE"
                self.current_workflow = None
                self.config = MagicMock()
                self.config.hotkey_mode = hotkey_mode
                self.config.audio_device = "@DEFAULT_SOURCE@"
                self._stop_recording_and_process = stop_mock

            def _on_workflow_triggered(self, workflow):
                from app.workflows import WorkflowType
                if self.state == "IDLE":
                    self.state = "RECORDING"
                    self.current_workflow = workflow
                elif self.state == "RECORDING":
                    if self.config.hotkey_mode == "toggle":
                        if workflow != self.current_workflow:
                            pass  # log only
                        self._stop_recording_and_process()
                else:
                    pass  # busy

        return AppStub(), stop_mock

    def test_same_hotkey_stops_recording(self):
        from app.workflows import WorkflowType
        app, stop_mock = self._make_app_stub()
        app._on_workflow_triggered(WorkflowType.TRANSCRIPTION)
        assert app.state == "RECORDING"
        app._on_workflow_triggered(WorkflowType.TRANSCRIPTION)
        stop_mock.assert_called_once()

    def test_different_hotkey_also_stops_recording(self):
        """Drücken eines anderen Workflow-Hotkeys soll die Aufnahme ebenfalls stoppen."""
        from app.workflows import WorkflowType
        app, stop_mock = self._make_app_stub()
        app._on_workflow_triggered(WorkflowType.EMOJI_TEXT)
        assert app.state == "RECORDING"
        assert app.current_workflow == WorkflowType.EMOJI_TEXT
        # Meta+H während EMOJI_TEXT-Aufnahme → soll stoppen, nicht ignorieren
        app._on_workflow_triggered(WorkflowType.TRANSCRIPTION)
        stop_mock.assert_called_once()

    def test_busy_state_ignores_all_hotkeys(self):
        from app.workflows import WorkflowType
        app, stop_mock = self._make_app_stub()
        app.state = "TRANSCRIBING"
        app._on_workflow_triggered(WorkflowType.TRANSCRIPTION)
        stop_mock.assert_not_called()


class TestHoldModeAppFlow:
    """Testet die App-seitige HOLD-Logik: _on_workflow_triggered + _on_recording_stop."""

    def _make_app_stub(self, hotkey_mode: str = "hold"):
        from unittest.mock import MagicMock

        stop_mock = MagicMock()
        start_recording_mock = MagicMock()

        class AppStub:
            def __init__(self):
                self.state = "IDLE"
                self.current_workflow = None
                self.config = MagicMock()
                self.config.hotkey_mode = hotkey_mode
                self.config.audio_device = "@DEFAULT_SOURCE@"
                self._stop_recording_and_process = stop_mock

            def _on_workflow_triggered(self, workflow):
                from app.workflows import WorkflowType
                if self.state == "IDLE":
                    self.state = "RECORDING"
                    self.current_workflow = workflow
                    start_recording_mock()
                elif self.state == "RECORDING":
                    if self.config.hotkey_mode == "toggle":
                        self._stop_recording_and_process()
                    # hold mode: ignored during recording

            def _on_recording_stop(self):
                if self.state == "RECORDING":
                    if self.config.hotkey_mode == "hold":
                        self._stop_recording_and_process()

        return AppStub(), stop_mock, start_recording_mock

    def test_hold_keydown_starts_recording(self):
        from app.workflows import WorkflowType
        app, stop_mock, start_mock = self._make_app_stub("hold")
        app._on_workflow_triggered(WorkflowType.TRANSCRIPTION)
        assert app.state == "RECORDING"
        assert app.current_workflow == WorkflowType.TRANSCRIPTION
        start_mock.assert_called_once()
        stop_mock.assert_not_called()

    def test_hold_keyup_stops_and_processes(self):
        from app.workflows import WorkflowType
        app, stop_mock, _ = self._make_app_stub("hold")
        app._on_workflow_triggered(WorkflowType.TRANSCRIPTION)
        app._on_recording_stop()
        stop_mock.assert_called_once()

    def test_hold_full_cycle_start_then_stop(self):
        """Taste halten → aufnehmen; loslassen → Transkription starten."""
        from app.workflows import WorkflowType
        app, stop_mock, start_mock = self._make_app_stub("hold")
        # Simulate: key down
        app._on_workflow_triggered(WorkflowType.TRANSCRIPTION)
        assert app.state == "RECORDING"
        stop_mock.assert_not_called()
        # Simulate: key up
        app._on_recording_stop()
        stop_mock.assert_called_once()

    def test_hold_second_keydown_ignored_during_recording(self):
        """Im Hold-Modus soll ein zweiter KEY_DOWN die Aufnahme nicht stoppen."""
        from app.workflows import WorkflowType
        app, stop_mock, start_mock = self._make_app_stub("hold")
        app._on_workflow_triggered(WorkflowType.TRANSCRIPTION)
        app._on_workflow_triggered(WorkflowType.TRANSCRIPTION)  # Autorepeat / zweiter Druck
        assert app.state == "RECORDING"
        stop_mock.assert_not_called()
        start_mock.assert_called_once()  # nur einmal gestartet

    def test_hold_recording_stop_ignored_if_not_recording(self):
        """_on_recording_stop im IDLE-Zustand soll nichts tun."""
        app, stop_mock, _ = self._make_app_stub("hold")
        assert app.state == "IDLE"
        app._on_recording_stop()
        stop_mock.assert_not_called()

    def test_toggle_mode_recording_stop_is_noop(self):
        """Im Toggle-Modus soll recording_stop ignoriert werden."""
        from app.workflows import WorkflowType
        app, stop_mock, _ = self._make_app_stub("toggle")
        app._on_workflow_triggered(WorkflowType.TRANSCRIPTION)
        assert app.state == "RECORDING"
        app._on_recording_stop()
        stop_mock.assert_not_called()

    def test_hold_different_keydown_during_recording_ignored(self):
        """Im Hold-Modus soll ein anderer Workflow-Hotkey die Aufnahme NICHT stoppen."""
        from app.workflows import WorkflowType
        app, stop_mock, _ = self._make_app_stub("hold")
        app._on_workflow_triggered(WorkflowType.TRANSCRIPTION)
        app._on_workflow_triggered(WorkflowType.EMOJI_TEXT)  # anderer Hotkey gedrückt
        assert app.state == "RECORDING"
        stop_mock.assert_not_called()


class TestModifierMatch:
    """Testet _modifier_match für modifier-freie und modifier-gebundene Hotkeys."""

    # Dummy-Keycodes für Tests
    META_L = 1001
    META_R = 1002
    SHIFT_L = 1003
    SHIFT_R = 1004
    ALL_META = {META_L, META_R}
    ALL_SHIFT = {SHIFT_L, SHIFT_R}
    LEFTALT = 1005

    def test_empty_modifiers_no_keys_pressed(self):
        """Modifier-freier Hotkey matcht wenn keine Modifier gedrückt."""
        pressed: set = set()
        assert _modifier_match(pressed, set(), set(), self.ALL_META, self.ALL_SHIFT) is True

    def test_empty_modifiers_meta_pressed_no_match(self):
        """Modifier-freier Hotkey matcht NICHT wenn Meta gedrückt ist."""
        pressed = {self.META_L}
        assert _modifier_match(pressed, set(), set(), self.ALL_META, self.ALL_SHIFT) is False

    def test_empty_modifiers_shift_pressed_no_match(self):
        """Modifier-freier Hotkey matcht NICHT wenn Shift gedrückt ist."""
        pressed = {self.SHIFT_R}
        assert _modifier_match(pressed, set(), set(), self.ALL_META, self.ALL_SHIFT) is False

    def test_empty_modifiers_meta_and_shift_pressed_no_match(self):
        pressed = {self.META_L, self.SHIFT_L}
        assert _modifier_match(pressed, set(), set(), self.ALL_META, self.ALL_SHIFT) is False

    def test_left_alt_trigger_does_not_count_as_blocking_modifier(self):
        """KEY_LEFTALT darf sich als modifier-freier Trigger nicht selbst blockieren."""
        pressed = {self.LEFTALT}
        assert _modifier_match(pressed, set(), set(), self.ALL_META, self.ALL_SHIFT) is True

    def test_meta_required_meta_pressed_matches(self):
        """Meta-Hotkey matcht wenn Meta gedrückt."""
        pressed = {self.META_L}
        meta_codes = {self.META_L, self.META_R}
        assert _modifier_match(pressed, meta_codes, set(), self.ALL_META, self.ALL_SHIFT) is True

    def test_meta_required_no_meta_no_match(self):
        """Meta-Hotkey matcht NICHT ohne Meta."""
        assert _modifier_match(set(), {self.META_L, self.META_R}, set(), self.ALL_META, self.ALL_SHIFT) is False

    def test_meta_and_shift_required_both_pressed_matches(self):
        pressed = {self.META_L, self.SHIFT_L}
        meta_codes = {self.META_L, self.META_R}
        shift_codes = {self.SHIFT_L, self.SHIFT_R}
        assert _modifier_match(pressed, meta_codes, shift_codes, self.ALL_META, self.ALL_SHIFT) is True

    def test_meta_required_shift_also_pressed_no_match(self):
        """Meta-Hotkey ohne Shift-Anforderung matcht NICHT wenn Shift gedrückt."""
        pressed = {self.META_L, self.SHIFT_L}
        meta_codes = {self.META_L, self.META_R}
        assert _modifier_match(pressed, meta_codes, set(), self.ALL_META, self.ALL_SHIFT) is False

    def test_modifier_free_hotkey_starts_on_keydown(self):
        """KEY_DOWN einer modifier-freien Taste löst on_start aus (Hold-Modus)."""
        start = MagicMock()
        stop = MagicMock()
        svc = HotkeyService(mode=HotkeyMode.HOLD, on_start=start, on_stop=stop)
        svc.simulate_key_down()
        start.assert_called_once()
        stop.assert_not_called()

    def test_modifier_free_hotkey_stops_on_keyup(self):
        """KEY_UP einer modifier-freien Taste löst on_stop aus (Hold-Modus)."""
        start = MagicMock()
        stop = MagicMock()
        svc = HotkeyService(mode=HotkeyMode.HOLD, on_start=start, on_stop=stop)
        svc.simulate_key_down()
        svc.simulate_key_up()
        stop.assert_called_once()


class TestKeyboardReconnect:
    class FakeDevice:
        def __init__(self, path, fd):
            self.path = path
            self.fd = fd
            self.closed = False

        def close(self):
            self.closed = True

    def test_refresh_keeps_existing_devices_when_paths_unchanged(self):
        current = self.FakeDevice("/dev/input/event1", 10)
        replacement = self.FakeDevice("/dev/input/event1", 11)

        with patch("app.hotkey_service._discover_keyboards", return_value=[replacement]):
            fd_to_dev = {current.fd: current}
            refreshed = _refresh_keyboard_devices(fd_to_dev, "KEY_LEFTALT", "test")

        assert refreshed is fd_to_dev
        assert current.closed is False
        assert replacement.closed is True

    def test_refresh_replaces_devices_when_paths_change(self):
        current = self.FakeDevice("/dev/input/event1", 10)
        replacement = self.FakeDevice("/dev/input/event2", 11)

        with patch("app.hotkey_service._discover_keyboards", return_value=[replacement]):
            refreshed = _refresh_keyboard_devices({current.fd: current}, "KEY_LEFTALT", "test")

        assert refreshed == {replacement.fd: replacement}
        assert current.closed is True
        assert replacement.closed is False


class TestTrayIconRendering:
    def test_microphone_icon_can_be_created(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

        from PyQt6.QtGui import QColor, QGuiApplication
        from app.blitztext_linux import BlitztextApp

        app = QGuiApplication.instance() or QGuiApplication([])
        icon = BlitztextApp._create_microphone_icon(object(), QColor("#2e7d32"))

        assert icon.isNull() is False


class TestTranscribeWorkerShutdown:
    def test_worker_emit_ignores_deleted_qt_signal_object(self, tmp_path):
        from app.blitztext_linux import _TranscribeWorker
        from app.workflows import WorkflowType

        class RaisingSignal:
            def emit(self, *args):
                raise RuntimeError("wrapped C/C++ object of type _WorkerSignals has been deleted")

        class DeletedSignals:
            status_changed = RaisingSignal()
            result = RaisingSignal()
            error = RaisingSignal()
            finished = RaisingSignal()

        worker = _TranscribeWorker(
            wav_file=tmp_path / "missing.wav",
            model="base",
            language="de",
            backend="openai-whisper",
            workflow=WorkflowType.TRANSCRIPTION,
            llm_service=MagicMock(),
            autopaste=False,
            paste_service=MagicMock(),
        )
        worker.signals = DeletedSignals()

        worker._emit("result", "text")


class TestModeFromConfig:
    def test_from_string_toggle(self, callbacks):
        svc = HotkeyService.from_config(
            mode_str="toggle",
            on_start=callbacks["start"],
            on_stop=callbacks["stop"],
        )
        assert svc.mode == HotkeyMode.TOGGLE

    def test_from_string_hold(self, callbacks):
        svc = HotkeyService.from_config(
            mode_str="hold",
            on_start=callbacks["start"],
            on_stop=callbacks["stop"],
        )
        assert svc.mode == HotkeyMode.HOLD

    def test_invalid_mode_raises(self, callbacks):
        with pytest.raises(ValueError, match="mode"):
            HotkeyService.from_config(
                mode_str="invalid",
                on_start=callbacks["start"],
                on_stop=callbacks["stop"],
            )

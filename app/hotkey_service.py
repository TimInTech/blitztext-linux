"""HotkeyService for BlitztextLinux.

Verwaltet alle 5 Workflow-Hotkeys via evdev.
Unterstützt zwei Modi:
  - toggle: einmal drücken = starten, nochmal = stoppen (Standard)
  - hold:   Taste halten = aufnehmen, loslassen = stoppen
"""
from __future__ import annotations

import os
import time
import logging
from enum import Enum
from typing import Dict, List, Optional, Set, Callable, Any

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from app.workflows import WorkflowType

DEBOUNCE_SECONDS = 0.6
DEVICE_REFRESH_SECONDS = 5.0
logger = logging.getLogger("blitztext.hotkey")

# Hotkey-Definitionen: WorkflowType -> (modifier_set, trigger_key_name)
_HOTKEY_MAP = [
    # (workflow, trigger_key, required_modifiers)
    (WorkflowType.TRANSCRIPTION,  "KEY_LEFTALT", set()),
    (WorkflowType.LOCAL,          "KEY_H", {"KEY_LEFTMETA", "KEY_RIGHTMETA", "KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"}),
    (WorkflowType.TEXT_IMPROVER,  "KEY_T", {"KEY_LEFTMETA", "KEY_RIGHTMETA", "KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"}),
    (WorkflowType.DAMPF_ABLASSEN, "KEY_D", {"KEY_LEFTMETA", "KEY_RIGHTMETA", "KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"}),
    (WorkflowType.EMOJI_TEXT,     "KEY_E", {"KEY_LEFTMETA", "KEY_RIGHTMETA", "KEY_LEFTSHIFT", "KEY_RIGHTSHIFT"}),
]

# Alle bekannten Meta- und Shift-Keycodes (als Namen; werden zur Laufzeit in Codes umgewandelt)
_ALL_META_KEY_NAMES = ("KEY_LEFTMETA", "KEY_RIGHTMETA")
_ALL_SHIFT_KEY_NAMES = ("KEY_LEFTSHIFT", "KEY_RIGHTSHIFT")
_DEBUG_MODIFIER_KEY_NAMES = (
    "KEY_LEFTALT", "KEY_RIGHTALT",
    "KEY_LEFTCTRL", "KEY_RIGHTCTRL",
    "KEY_LEFTMETA", "KEY_RIGHTMETA",
    "KEY_LEFTSHIFT", "KEY_RIGHTSHIFT",
)


def _modifier_match(
    pressed: Set[int],
    meta_codes: Set[int],
    shift_codes: Set[int],
    all_meta_codes: Set[int],
    all_shift_codes: Set[int],
) -> bool:
    """Prüft ob der aktuelle Modifier-Status zur Hotkey-Definition passt.

    Leere modifier_set bedeutet: kein Modifier nötig (und keiner darf gedrückt sein).
    """
    result = True
    reason = "match"

    if meta_codes:
        if not any(m in pressed for m in meta_codes):
            result = False
            reason = "missing_meta"
    elif any(m in pressed for m in all_meta_codes):
        result = False
        reason = "unexpected_meta"

    if result and shift_codes:
        if not any(s in pressed for s in shift_codes):
            result = False
            reason = "missing_shift"
    elif result and any(s in pressed for s in all_shift_codes):
        result = False
        reason = "unexpected_shift"

    logger.debug(
        "modifier_match result=%s reason=%s pressed=%s required_meta=%s required_shift=%s all_meta=%s all_shift=%s",
        result, reason, sorted(pressed), sorted(meta_codes), sorted(shift_codes),
        sorted(all_meta_codes), sorted(all_shift_codes),
    )
    return result


class HotkeyMode(str, Enum):
    TOGGLE = "toggle"
    HOLD = "hold"


class HotkeyService:
    """Mockable Hotkey Service logic used by tests."""

    def __init__(
        self,
        mode: HotkeyMode,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
    ) -> None:
        self.mode = mode
        self.on_start = on_start
        self.on_stop = on_stop
        self.debounce_interval = 0.6
        self.is_recording = False
        self.last_toggle_time = 0.0

    @classmethod
    def from_config(
        cls,
        mode_str: str,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
    ) -> HotkeyService:
        try:
            mode = HotkeyMode(mode_str)
        except ValueError:
            raise ValueError(f"invalid hotkey mode: {mode_str}")
        return cls(mode, on_start, on_stop)

    def simulate_key_down(self) -> None:
        if self.mode == HotkeyMode.TOGGLE:
            if not self.is_recording:
                self.is_recording = True
                self.on_start()
            else:
                self.is_recording = False
                self.on_stop()
        elif self.mode == HotkeyMode.HOLD:
            if not self.is_recording:
                self.is_recording = True
                self.on_start()

    def simulate_key_up(self) -> None:
        if self.mode == HotkeyMode.HOLD:
            if self.is_recording:
                self.is_recording = False
                self.on_stop()


class HotkeyWorker(QObject):
    """Evdev-Hotkey-Loop für BlitztextLinux.

    Wird in einem QThread ausgeführt.
    """

    workflow_triggered = pyqtSignal(object)   # WorkflowType
    recording_stop = pyqtSignal()             # nur im Hold-Modus
    error = pyqtSignal(str)

    def __init__(
        self,
        hotkey_mode: str = "toggle",
        transcription_key: str = "KEY_LEFTALT",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        if hotkey_mode not in ("toggle", "hold"):
            raise ValueError(f"hotkey_mode muss 'toggle' oder 'hold' sein, nicht {hotkey_mode!r}")
        self._mode = hotkey_mode
        self._transcription_key = transcription_key
        self._running = False

    @pyqtSlot()
    def run(self) -> None:
        """Haupt-Evdev-Loop. Läuft bis stop() aufgerufen wird."""
        try:
            from evdev import InputDevice, ecodes, list_devices  # noqa: PLC0415
        except ImportError:
            self.error.emit("python3-evdev nicht installiert (pip install evdev)")
            return

        import select as sel  # noqa: PLC0415

        devices = _discover_keyboards(self._transcription_key)
        if not devices:
            self.error.emit(_build_missing_keyboard_message())
            return

        fd_to_dev: Dict[int, InputDevice] = {dev.fd: dev for dev in devices}
        pressed: Set[int] = set()
        last_trigger: Dict[WorkflowType, float] = {}
        _hold_active: Optional[WorkflowType] = None

        from evdev import ecodes as ec  # noqa: PLC0415
        all_meta_codes = {
            getattr(ec, k) for k in _ALL_META_KEY_NAMES if hasattr(ec, k)
        }
        all_shift_codes = {
            getattr(ec, k) for k in _ALL_SHIFT_KEY_NAMES if hasattr(ec, k)
        }
        debug_modifier_codes = {
            getattr(ec, k): k for k in _DEBUG_MODIFIER_KEY_NAMES if hasattr(ec, k)
        }

        hotkeys = []
        for workflow, tkey, mod_names in _HOTKEY_MAP:
            if workflow == WorkflowType.TRANSCRIPTION:
                tkey = self._transcription_key
            tcode = getattr(ec, tkey, None)
            if tcode is None:
                continue
            meta_codes = {
                getattr(ec, k) for k in mod_names
                if k in _ALL_META_KEY_NAMES and hasattr(ec, k)
            }
            shift_codes = {
                getattr(ec, k) for k in mod_names
                if k in _ALL_SHIFT_KEY_NAMES and hasattr(ec, k)
            }
            hotkeys.append((workflow, tcode, meta_codes, shift_codes))

        self._running = True
        next_device_refresh = time.monotonic() + DEVICE_REFRESH_SECONDS
        logger.debug(
            "Hotkey worker started mode=%s transcription_key=%s devices=%s wayland=%s display=%s",
            self._mode, self._transcription_key, _device_paths(fd_to_dev.values()),
            bool(os.environ.get("WAYLAND_DISPLAY")), bool(os.environ.get("DISPLAY")),
        )
        while self._running:
            try:
                rlist, _, _ = sel.select(list(fd_to_dev.keys()), [], [], 1.0)
            except (ValueError, OSError):
                time.sleep(1)
                devices = _discover_keyboards(self._transcription_key)
                if not devices:
                    time.sleep(5)
                    devices = _discover_keyboards(self._transcription_key)
                    if not devices:
                        self.error.emit(_build_missing_keyboard_message("nach Wiederverbindung"))
                        return
                fd_to_dev = {dev.fd: dev for dev in devices}
                pressed.clear()
                _hold_active = None
                next_device_refresh = time.monotonic() + DEVICE_REFRESH_SECONDS
                logger.debug("Keyboard devices reconnected after select error: %s", _device_paths(devices))
                continue

            if time.monotonic() >= next_device_refresh:
                new_fd_to_dev = _refresh_keyboard_devices(
                    fd_to_dev, self._transcription_key, reason="periodic"
                )
                if new_fd_to_dev is not fd_to_dev:
                    fd_to_dev = new_fd_to_dev
                    pressed.clear()
                    _hold_active = None
                next_device_refresh = time.monotonic() + DEVICE_REFRESH_SECONDS

            for fd in rlist:
                dev = fd_to_dev.get(fd)
                if dev is None:
                    continue
                try:
                    events = list(dev.read())
                    if not events:
                        new_fd_to_dev = _refresh_keyboard_devices(
                            fd_to_dev, self._transcription_key, reason="empty_read"
                        )
                        if new_fd_to_dev is not fd_to_dev:
                            fd_to_dev = new_fd_to_dev
                            pressed.clear()
                            _hold_active = None
                        continue

                    for event in events:
                        if event.type != ec.EV_KEY:
                            continue
                        code = event.code
                        value = event.value  # 1=down, 0=up, 2=repeat

                        if value == 1:
                            pressed.add(code)
                        elif value == 0:
                            pressed.discard(code)

                        key_name = _key_name(ec, code)
                        active_modifiers = sorted(
                            name for mod_code, name in debug_modifier_codes.items()
                            if mod_code in pressed
                        )
                        logger.debug(
                            "evdev key event device=%s key=%s code=%s value=%s active_modifiers=%s",
                            getattr(dev, "path", "<unknown>"), key_name, code, value, active_modifiers,
                        )

                        # --- Hold-Modus: KEY_UP des aktiven Trigger-Keys stoppt ---
                        if self._mode == "hold" and value == 0 and _hold_active is not None:
                            for wf, tcode, _, _ in hotkeys:
                                if wf == _hold_active and code == tcode:
                                    self.recording_stop.emit()
                                    _hold_active = None
                                    break

                        if value != 1:
                            continue  # nur KEY_DOWN-Events triggern

                        for workflow, tcode, meta_codes, shift_codes in hotkeys:
                            if code != tcode:
                                continue
                            if not _modifier_match(
                                pressed, meta_codes, shift_codes,
                                all_meta_codes, all_shift_codes,
                            ):
                                continue

                            now = time.monotonic()
                            if now - last_trigger.get(workflow, 0.0) < DEBOUNCE_SECONDS:
                                break
                            last_trigger[workflow] = now

                            self.workflow_triggered.emit(workflow)
                            if self._mode == "hold":
                                _hold_active = workflow
                            break

                except OSError:
                    fd_to_dev.pop(fd, None)
                    fd_to_dev = _refresh_keyboard_devices(
                        fd_to_dev, self._transcription_key, reason="read_error"
                    )
                    pressed.clear()
                    _hold_active = None
                    break

    def stop(self) -> None:
        self._running = False


def _discover_keyboards(transcription_key: str = "KEY_LEFTALT") -> list:
    try:
        from evdev import InputDevice, ecodes, list_devices  # noqa: PLC0415
    except ImportError:
        return []

    devices = []
    fallback_candidates = []
    for path in list_devices():
        try:
            dev = InputDevice(path)
            caps = dev.capabilities().get(ecodes.EV_KEY, [])
            has_meta = any(k in caps for k in (ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA))
            has_trigger = any(getattr(ecodes, tkey, None) in caps for tkey in _known_hotkey_keys(transcription_key))
            if has_meta and has_trigger:
                devices.append(dev)
            elif has_trigger:
                fallback_candidates.append(dev)
            else:
                dev.close()
        except (PermissionError, OSError):
            pass

    if devices:
        for dev in fallback_candidates:
            try:
                dev.close()
            except Exception:
                pass
        return devices

    if fallback_candidates:
        import sys
        print(
            "Warning: no keyboard with Meta key found, falling back",
            file=sys.stderr, flush=True,
        )
        for dev in fallback_candidates[1:]:
            try:
                dev.close()
            except Exception:
                pass
        return fallback_candidates[:1]

    return []


def _known_hotkey_keys(transcription_key: str) -> Set[str]:
    keys = {tkey for _, tkey, _ in _HOTKEY_MAP}
    keys.add(transcription_key)
    return keys


def _device_paths(devices) -> Set[str]:
    return {getattr(dev, "path", str(getattr(dev, "fd", dev))) for dev in devices}


def _close_devices(devices) -> None:
    for dev in list(devices):
        try:
            dev.close()
        except Exception:
            pass


def _refresh_keyboard_devices(fd_to_dev: Dict[int, Any], transcription_key: str, reason: str) -> Dict[int, Any]:
    devices = _discover_keyboards(transcription_key)
    if not devices:
        logger.debug("Keyboard refresh (%s): no replacement devices found; keeping current devices", reason)
        return fd_to_dev

    current_paths = _device_paths(fd_to_dev.values())
    new_paths = _device_paths(devices)
    if current_paths == new_paths:
        _close_devices(devices)
        logger.debug("Keyboard refresh (%s): devices unchanged: %s", reason, sorted(current_paths))
        return fd_to_dev

    logger.debug(
        "Keyboard refresh (%s): devices changed old=%s new=%s",
        reason, sorted(current_paths), sorted(new_paths),
    )
    _close_devices(fd_to_dev.values())
    return {dev.fd: dev for dev in devices}


def _key_name(ecodes, code: int) -> str:
    name = ecodes.KEY.get(code) if hasattr(ecodes, "KEY") else None
    if isinstance(name, list):
        return "/".join(str(part) for part in name)
    if name:
        return str(name)
    return str(code)


def _group_names() -> Set[str]:
    try:
        import grp
        return {grp.getgrgid(gid).gr_name for gid in os.getgroups()}
    except Exception:
        return set()


def _build_missing_keyboard_message(context: str = "") -> str:
    suffix = f" {context}" if context else ""
    hints = []
    if not os.path.exists("/dev/uinput"):
        hints.append("/dev/uinput fehlt")
    if "input" not in _group_names():
        hints.append("Benutzer nicht in Gruppe 'input'")
    if not os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        hints.append("keine GUI-Session")
    hint_text = f" ({'; '.join(hints)})" if hints else ""
    return f"Keine Tastatur-Geraete gefunden{suffix}{hint_text}"

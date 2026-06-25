from unittest.mock import MagicMock, call

from app.blitztext_linux import BlitztextApp, _is_hotkey_device_access_error


def test_hotkey_device_access_error_detects_missing_keyboard():
    assert _is_hotkey_device_access_error("Keine Tastatur-Geraete gefunden")


def test_hotkey_device_access_error_detects_input_group_hint():
    assert _is_hotkey_device_access_error("Benutzer nicht in Gruppe 'input'")


def test_hotkey_device_access_error_detects_evdev_dependency():
    assert _is_hotkey_device_access_error("python3-evdev nicht installiert")


def test_hotkey_device_access_error_ignores_unrelated_errors():
    assert not _is_hotkey_device_access_error("Audioaufnahme konnte nicht gestartet werden")


# ---------------------------------------------------------------------------
# _on_hotkey_error Slot
# ---------------------------------------------------------------------------

def test_on_hotkey_error_device_access_calls_tray_warning():
    """Device-Access-Fehler → show_tray_warning, kein show_tray_error."""
    self = MagicMock()
    err = "Keine Tastatur-Geraete gefunden"
    BlitztextApp._on_hotkey_error(self, err)
    self.show_tray_warning.assert_called_once_with(
        "Hotkey Hinweis",
        f"{err}\nStart/Stopp läuft über Fenster/Tray.",
    )
    self.show_tray_error.assert_not_called()


def test_on_hotkey_error_generic_error_calls_tray_error():
    """Nicht klassifizierter Fehler → show_tray_error, kein show_tray_warning."""
    self = MagicMock()
    err = "Audioaufnahme konnte nicht gestartet werden"
    BlitztextApp._on_hotkey_error(self, err)
    self.show_tray_error.assert_called_once_with("Hotkey Fehler", err)
    self.show_tray_warning.assert_not_called()

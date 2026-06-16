from app.blitztext_linux import _is_hotkey_device_access_error


def test_hotkey_device_access_error_detects_missing_keyboard():
    assert _is_hotkey_device_access_error("Keine Tastatur-Geraete gefunden")


def test_hotkey_device_access_error_detects_input_group_hint():
    assert _is_hotkey_device_access_error("Benutzer nicht in Gruppe 'input'")


def test_hotkey_device_access_error_detects_evdev_dependency():
    assert _is_hotkey_device_access_error("python3-evdev nicht installiert")


def test_hotkey_device_access_error_ignores_unrelated_errors():
    assert not _is_hotkey_device_access_error("Audioaufnahme konnte nicht gestartet werden")

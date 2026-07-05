import pytest
from unittest.mock import patch, MagicMock

from app.paste_service import PasteService, check_dependencies
from app.hotkey_service import _build_missing_keyboard_message


# 1. PasteService.check_dependencies()
def test_check_dependencies_flatpak():
    def mock_exists(path):
        return path == "/.flatpak-info"

    def mock_which(cmd):
        return None  # wl-copy, xclip, ydotool als fehlend

    with patch("app.paste_service.os.path.exists", side_effect=mock_exists), \
         patch("app.paste_service.shutil.which", side_effect=mock_which):
        missing = check_dependencies()
        assert missing == []  # Keine harte fehlende Abhängigkeit im Flatpak


def test_check_dependencies_no_flatpak():
    def mock_exists(path):
        return False

    def mock_which(cmd):
        return None

    with patch("app.paste_service.os.path.exists", side_effect=mock_exists), \
         patch("app.paste_service.shutil.which", side_effect=mock_which):
        missing = check_dependencies()
        assert "wl-clipboard oder xclip" in missing
        assert "ydotool" in missing


# 2. HotkeyService Flatpak-Hinweis
def test_hotkey_service_flatpak_hint():
    def mock_exists(path):
        return path == "/.flatpak-info"

    with patch("app.hotkey_service.os.path.exists", side_effect=mock_exists):
        msg = _build_missing_keyboard_message()
        assert msg == "Globale Hotkeys sind im Flatpak nicht verfügbar"


# 3. PasteService Auto-Paste ohne ydotool
def test_paste_service_autopaste_without_ydotool():
    def mock_which(cmd):
        if cmd == "ydotool":
            return None
        if cmd == "wl-copy":
            return "/usr/bin/wl-copy"
        return None

    svc = PasteService(autopaste=True)
    
    with patch("app.paste_service.shutil.which", side_effect=mock_which), \
         patch("app.paste_service._has_wayland_clipboard", return_value=True), \
         patch("app.paste_service.PasteService._wl_copy") as mock_wl_copy, \
         patch("app.paste_service.PasteService._ydotool_paste") as mock_ydotool:
        
        svc.paste("test text")
        
        # Clipboard copy continues
        mock_wl_copy.assert_called_once_with("test text")
        
        # Auto-Paste is skipped, no ydotool called
        mock_ydotool.assert_not_called()


# 4. PasteService Qt-Clipboard-Fallback
def test_paste_service_qt_clipboard_fallback():
    svc = PasteService(autopaste=False)
    
    with patch("app.paste_service._has_wayland_clipboard", return_value=False), \
         patch("app.paste_service._has_x11_clipboard", return_value=False), \
         patch("app.paste_service._has_qt_clipboard", return_value=True), \
         patch("app.paste_service.PasteService._qt_copy") as mock_qt_copy:
         
        svc.paste("fallback text")
        mock_qt_copy.assert_called_once_with("fallback text")


def test_paste_service_qt_read_thread_safety():
    svc = PasteService(autopaste=False)
    
    app_mock = MagicMock()
    app_mock.thread.return_value = "main_thread"
    
    cb_mock = MagicMock()
    cb_mock.text.return_value = "clipboard content"
    app_mock.clipboard.return_value = cb_mock

    def mock_current_thread_gui():
        return "main_thread"

    def mock_current_thread_other():
        return "other_thread"

    # Test 1: GUI Thread reads successfully
    with patch("PyQt6.QtWidgets.QApplication.instance", return_value=app_mock), \
         patch("PyQt6.QtCore.QThread.currentThread", side_effect=mock_current_thread_gui):
         
        result = svc._qt_read()
        assert result == "clipboard content"

    # Test 2: Non-GUI Thread returns None
    with patch("PyQt6.QtWidgets.QApplication.instance", return_value=app_mock), \
         patch("PyQt6.QtCore.QThread.currentThread", side_effect=mock_current_thread_other):
         
        result = svc._qt_read()
        assert result is None

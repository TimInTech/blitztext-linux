from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock, patch

from app.paste_service import (
    _CTRL_SHIFT_V_KEYCODES,
    _CTRL_V_KEYCODES,
    _PASTE_DELAY,
    _XDOTOOL_TIMEOUT,
    _WL_PASTE_TIMEOUT,
    _XCLIP_PASTE_TIMEOUT,
    PasteService,
    PasteServiceError,
    _detect_active_window_class,
    _is_terminal_active,
)


class TestDetectActiveWindowClass:
    def test_returns_lowercase_class_on_success(self):
        result = MagicMock(stdout="Konsole\n", returncode=0)
        with patch.dict(os.environ, {"DISPLAY": ":0"}, clear=False):
            with patch("app.paste_service.shutil.which", return_value="/usr/bin/xdotool"):
                with patch("app.paste_service.subprocess.run", return_value=result) as run_mock:
                    assert _detect_active_window_class() == "konsole"
        run_mock.assert_called_once_with(
            ["xdotool", "getactivewindow", "getwindowclassname"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=_XDOTOOL_TIMEOUT,
        )

    def test_returns_none_if_xdotool_missing(self):
        with patch.dict(os.environ, {"DISPLAY": ":0"}, clear=False):
            with patch("app.paste_service.shutil.which", return_value=None):
                with patch("app.paste_service.subprocess.run") as run_mock:
                    assert _detect_active_window_class() is None
        run_mock.assert_not_called()

    def test_returns_none_on_timeout(self):
        with patch.dict(os.environ, {"DISPLAY": ":0"}, clear=False):
            with patch("app.paste_service.shutil.which", return_value="/usr/bin/xdotool"):
                with patch(
                    "app.paste_service.subprocess.run",
                    side_effect=subprocess.TimeoutExpired(cmd="xdotool", timeout=_XDOTOOL_TIMEOUT),
                ):
                    assert _detect_active_window_class() is None

    def test_returns_none_on_called_process_error(self):
        with patch.dict(os.environ, {"DISPLAY": ":0"}, clear=False):
            with patch("app.paste_service.shutil.which", return_value="/usr/bin/xdotool"):
                with patch(
                    "app.paste_service.subprocess.run",
                    side_effect=subprocess.CalledProcessError(
                        returncode=1,
                        cmd=["xdotool", "getactivewindow", "getwindowclassname"],
                    ),
                ):
                    assert _detect_active_window_class() is None

    def test_returns_none_on_oserror(self):
        with patch.dict(os.environ, {"DISPLAY": ":0"}, clear=False):
            with patch("app.paste_service.shutil.which", return_value="/usr/bin/xdotool"):
                with patch(
                    "app.paste_service.subprocess.run",
                    side_effect=OSError("boom"),
                ):
                    assert _detect_active_window_class() is None

    def test_returns_none_if_display_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch("app.paste_service.shutil.which") as which_mock:
                with patch("app.paste_service.subprocess.run") as run_mock:
                    assert _detect_active_window_class() is None
        which_mock.assert_not_called()
        run_mock.assert_not_called()


class TestIsTerminalActive:
    def test_returns_true_for_terminal_window(self):
        with patch("app.paste_service._detect_active_window_class", return_value="konsole"):
            assert _is_terminal_active() is True

    def test_returns_false_for_non_terminal_window(self):
        with patch("app.paste_service._detect_active_window_class", return_value="firefox"):
            assert _is_terminal_active() is False

    def test_returns_false_when_detection_is_none(self):
        with patch("app.paste_service._detect_active_window_class", return_value=None):
            assert _is_terminal_active() is False


class TestYdotoolPaste:
    def test_sends_ctrl_shift_v_when_terminal_active(self):
        service = PasteService(autopaste=True, key_delay_ms=135)
        result = MagicMock(returncode=0, stderr=b"")
        with patch("app.paste_service.shutil.which", return_value="/usr/bin/ydotool"):
            with patch("app.paste_service._is_terminal_active", return_value=True):
                with patch("app.paste_service.time.sleep"):
                    with patch("app.paste_service.subprocess.run", return_value=result) as run_mock:
                        assert service._ydotool_paste() is True
        run_mock.assert_called_once_with(
            ["ydotool", "key", "--key-delay", "135", *_CTRL_SHIFT_V_KEYCODES],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=5.0,
        )

    def test_sends_ctrl_v_when_non_terminal_active(self):
        service = PasteService(autopaste=True, key_delay_ms=246)
        result = MagicMock(returncode=0, stderr=b"")
        with patch("app.paste_service.shutil.which", return_value="/usr/bin/ydotool"):
            with patch("app.paste_service._is_terminal_active", return_value=False):
                with patch("app.paste_service.time.sleep"):
                    with patch("app.paste_service.subprocess.run", return_value=result) as run_mock:
                        assert service._ydotool_paste() is True
        run_mock.assert_called_once_with(
            ["ydotool", "key", "--key-delay", "246", *_CTRL_V_KEYCODES],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=5.0,
        )


class TestReadClipboard:
    def test_reads_wayland_clipboard_with_wl_paste(self):
        service = PasteService()
        process = MagicMock(returncode=0)
        process.communicate.return_value = (b"vorher", b"")
        with patch("app.paste_service._has_wayland_clipboard", return_value=True):
            with patch("app.paste_service.subprocess.Popen", return_value=process) as popen_mock:
                assert service._read_clipboard() == "vorher"
        popen_mock.assert_called_once_with(
            ["wl-paste", "--no-newline"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        process.communicate.assert_called_once_with(timeout=_WL_PASTE_TIMEOUT)

    def test_reads_x11_clipboard_with_xclip(self):
        service = PasteService()
        process = MagicMock(returncode=0)
        process.communicate.return_value = (b"vorher-x11", b"")
        with patch("app.paste_service._has_wayland_clipboard", return_value=False):
            with patch("app.paste_service._has_x11_clipboard", return_value=True):
                with patch("app.paste_service.subprocess.Popen", return_value=process) as popen_mock:
                    assert service._read_clipboard() == "vorher-x11"
        popen_mock.assert_called_once_with(
            ["xclip", "-selection", "clipboard", "-o"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        process.communicate.assert_called_once_with(timeout=_XCLIP_PASTE_TIMEOUT)

    def test_returns_none_on_timeout(self):
        service = PasteService()
        process = MagicMock()
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd="wl-paste", timeout=_WL_PASTE_TIMEOUT),
            (b"", b""),
        ]
        with patch("app.paste_service._has_wayland_clipboard", return_value=True):
            with patch("app.paste_service.subprocess.Popen", return_value=process):
                assert service._read_clipboard() is None
        process.kill.assert_called_once_with()

    def test_returns_none_on_error(self):
        service = PasteService()
        with patch("app.paste_service._has_wayland_clipboard", return_value=True):
            with patch("app.paste_service.subprocess.Popen", side_effect=OSError("boom")):
                assert service._read_clipboard() is None


class TestRestoreClipboard:
    def test_none_is_noop(self):
        service = PasteService()
        with patch.object(service, "_wl_copy") as wl_copy_mock:
            with patch.object(service, "_xclip_copy") as xclip_copy_mock:
                service._restore_clipboard(None)
        wl_copy_mock.assert_not_called()
        xclip_copy_mock.assert_not_called()

    def test_restores_wayland_clipboard_with_saved_text(self):
        service = PasteService()
        with patch("app.paste_service._has_wayland_clipboard", return_value=True):
            with patch.object(service, "_wl_copy") as wl_copy_mock:
                service._restore_clipboard("wiederherstellen")
        wl_copy_mock.assert_called_once_with("wiederherstellen")

    def test_restores_x11_clipboard_with_empty_string(self):
        service = PasteService()
        with patch("app.paste_service._has_wayland_clipboard", return_value=False):
            with patch("app.paste_service._has_x11_clipboard", return_value=True):
                with patch.object(service, "_xclip_copy") as xclip_copy_mock:
                    # "" ist ein gueltiger alter Clipboard-Inhalt und darf nicht wie None behandelt werden.
                    service._restore_clipboard("")
        xclip_copy_mock.assert_called_once_with("")

    def test_logs_warning_on_restore_failure(self):
        service = PasteService()
        with patch("app.paste_service._has_wayland_clipboard", return_value=True):
            with patch.object(service, "_wl_copy", side_effect=PasteServiceError("boom")):
                with patch("app.paste_service.logger.warning") as warning_mock:
                    service._restore_clipboard("vorher")
        warning_mock.assert_called_once_with("Originalzwischenablage konnte nicht wiederhergestellt werden")


class TestPasteClipboardRestore:
    def test_paste_restores_clipboard_after_successful_autopaste(self):
        service = PasteService(autopaste=True)
        calls: list[str] = []

        with patch.object(service, "_read_clipboard", side_effect=lambda: calls.append("read") or "vorher"):
            with patch.object(service, "_copy_to_clipboard", side_effect=lambda text: calls.append(f"copy:{text}")):
                with patch.object(service, "_ydotool_paste", side_effect=lambda: calls.append("ydotool") or True):
                    with patch("app.paste_service.time.sleep", side_effect=lambda _: calls.append("sleep")):
                        with patch.object(
                            service,
                            "_restore_clipboard",
                            side_effect=lambda value: calls.append(f"restore:{value}"),
                        ):
                            service.paste("neu", force_autopaste=True)

        assert calls == ["read", "copy:neu", "ydotool", "sleep", "restore:vorher"]

    def test_paste_does_not_restore_when_autopaste_disabled(self):
        service = PasteService(autopaste=True)
        with patch.object(service, "_read_clipboard") as read_mock:
            with patch.object(service, "_copy_to_clipboard") as copy_mock:
                with patch.object(service, "_ydotool_paste") as paste_mock:
                    with patch.object(service, "_restore_clipboard") as restore_mock:
                        service.paste("neu", force_autopaste=False)
        read_mock.assert_not_called()
        copy_mock.assert_called_once_with("neu")
        paste_mock.assert_not_called()
        restore_mock.assert_not_called()

    def test_paste_does_not_restore_when_ydotool_did_not_paste(self):
        service = PasteService(autopaste=True)
        with patch.object(service, "_read_clipboard", return_value="vorher") as read_mock:
            with patch.object(service, "_copy_to_clipboard") as copy_mock:
                with patch.object(service, "_ydotool_paste", return_value=False) as paste_mock:
                    with patch("app.paste_service.time.sleep") as sleep_mock:
                        with patch.object(service, "_restore_clipboard") as restore_mock:
                            service.paste("neu", force_autopaste=True)
        read_mock.assert_called_once_with()
        copy_mock.assert_called_once_with("neu")
        paste_mock.assert_called_once_with()
        sleep_mock.assert_not_called()
        restore_mock.assert_not_called()

    def test_paste_restores_empty_previous_clipboard_after_successful_autopaste(self):
        service = PasteService(autopaste=True)
        with patch.object(service, "_read_clipboard", return_value="") as read_mock:
            with patch.object(service, "_copy_to_clipboard") as copy_mock:
                with patch.object(service, "_ydotool_paste", return_value=True) as paste_mock:
                    with patch("app.paste_service.time.sleep") as sleep_mock:
                        with patch.object(service, "_restore_clipboard") as restore_mock:
                            service.paste("neu", force_autopaste=True)
        read_mock.assert_called_once_with()
        copy_mock.assert_called_once_with("neu")
        paste_mock.assert_called_once_with()
        sleep_mock.assert_called_once_with(_PASTE_DELAY)
        restore_mock.assert_called_once_with("")

    def test_clipboard_only_does_not_restore(self):
        service = PasteService(autopaste=True)
        with patch.object(service, "_read_clipboard") as read_mock:
            with patch.object(service, "_copy_to_clipboard") as copy_mock:
                with patch.object(service, "_restore_clipboard") as restore_mock:
                    service.clipboard_only("neu")
        read_mock.assert_not_called()
        copy_mock.assert_called_once_with("neu")
        restore_mock.assert_not_called()

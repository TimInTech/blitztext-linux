from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock, patch

from app.paste_service import (
    _CTRL_SHIFT_V_KEYCODES,
    _CTRL_V_KEYCODES,
    _XDOTOOL_TIMEOUT,
    PasteService,
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
                        service._ydotool_paste()
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
                        service._ydotool_paste()
        run_mock.assert_called_once_with(
            ["ydotool", "key", "--key-delay", "246", *_CTRL_V_KEYCODES],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=5.0,
        )

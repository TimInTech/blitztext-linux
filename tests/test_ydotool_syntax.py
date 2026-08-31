"""Regression coverage for ydotool shortcut syntax."""

from __future__ import annotations

import os
import subprocess
import unittest
from unittest.mock import patch

from app.paste_service import PasteService


class YdotoolSyntaxTests(unittest.TestCase):
    def test_wayland_terminal_fallback_uses_symbolic_ctrl_shift_v(self) -> None:
        """Ubuntu 24.04 ydotool 0.1.x parses numeric keycodes as text."""
        with (
            patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}, clear=True),
            patch("app.paste_service.shutil.which", return_value="/usr/bin/ydotool"),
            patch("app.paste_service._detect_active_window_class", return_value=None),
            patch.object(PasteService, "_ydotool_uses_legacy_key_syntax", return_value=True),
            patch("app.paste_service.time.sleep"),
            patch(
                "app.paste_service.subprocess.run",
                return_value=subprocess.CompletedProcess(["ydotool", "key"], 0, stderr=b""),
            ) as run,
        ):
            PasteService()._ydotool_paste()

        self.assertEqual(
            run.call_args.args[0],
            ["ydotool", "key", "--key-delay", "80", "ctrl+shift+v"],
        )

    def test_current_ydotool_keeps_terminal_keycodes(self) -> None:
        """ydotool >= 1.0 continues to receive its documented keycode syntax."""
        with (
            patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}, clear=True),
            patch("app.paste_service.shutil.which", return_value="/usr/bin/ydotool"),
            patch("app.paste_service._detect_active_window_class", return_value=None),
            patch.object(PasteService, "_ydotool_uses_legacy_key_syntax", return_value=False, create=True),
            patch("app.paste_service.time.sleep"),
            patch(
                "app.paste_service.subprocess.run",
                return_value=subprocess.CompletedProcess(["ydotool", "key"], 0, stderr=b""),
            ) as run,
        ):
            PasteService()._ydotool_paste()

        self.assertEqual(
            run.call_args.args[0],
            ["ydotool", "key", "--key-delay", "80", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"],
        )


if __name__ == "__main__":
    unittest.main()

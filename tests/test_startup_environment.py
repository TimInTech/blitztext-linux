"""Startup environment regression tests.

These cover the display-environment decisions before QApplication is created.
They are intentionally headless: no real Qt app, evdev, audio, or clipboard tools.
"""
from __future__ import annotations

import os

import pytest

from app.blitztext_linux import _configure_qt_platform, _require_display_environment


def test_require_display_environment_exits_when_no_display_is_available(monkeypatch, capsys):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        _require_display_environment()

    assert excinfo.value.code == 1
    assert "No usable display environment" in capsys.readouterr().err


def test_require_display_environment_infers_wayland_socket_from_runtime_dir(tmp_path, monkeypatch):
    socket_path = tmp_path / "wayland-1"
    socket_path.touch()
    # Track the variable with monkeypatch before the production helper mutates it,
    # otherwise the inferred value can leak into later clipboard tests.
    monkeypatch.setenv("WAYLAND_DISPLAY", "")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

    _require_display_environment()

    assert os.environ["WAYLAND_DISPLAY"] == "wayland-1"


def test_require_display_environment_falls_back_to_display_when_wayland_is_unusable(monkeypatch, capsys):
    monkeypatch.setenv("WAYLAND_DISPLAY", "missing-wayland-socket")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

    _require_display_environment()

    assert "WAYLAND_DISPLAY" not in os.environ
    assert "falling back to DISPLAY" in capsys.readouterr().err


def test_configure_qt_platform_prefers_existing_wayland_socket(tmp_path, monkeypatch):
    socket_path = tmp_path / "wayland-0"
    socket_path.touch()
    monkeypatch.delenv("QT_QPA_PLATFORM", raising=False)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    _configure_qt_platform()

    assert os.environ["QT_QPA_PLATFORM"] == "wayland"


def test_configure_qt_platform_respects_explicit_platform(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")

    _configure_qt_platform()

    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"

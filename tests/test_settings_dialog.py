"""Tests für SettingsDialog-Helfer ohne echten Editor oder GUI-Leaks."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from app.blitztext_linux import SettingsDialog
from app.config import BlitztextConfig


def _fake_self(config_dir):
    return SimpleNamespace(config=BlitztextConfig(config_dir=config_dir))


def test_open_config_creates_missing_file(tmp_path):
    fake = _fake_self(tmp_path / ".config" / "blitztext-linux")
    assert not fake.config.config_file.is_file()

    with patch("app.blitztext_linux.QDesktopServices.openUrl", return_value=True) as m_open, \
            patch("app.blitztext_linux.QMessageBox") as m_box:
        SettingsDialog._open_config_file(fake)

    assert fake.config.config_file.is_file()
    m_open.assert_called_once()
    m_box.warning.assert_not_called()
    m_box.critical.assert_not_called()


def test_open_config_passes_correct_local_path(tmp_path):
    fake = _fake_self(tmp_path / ".config" / "blitztext-linux")

    with patch("app.blitztext_linux.QDesktopServices.openUrl", return_value=True) as m_open, \
            patch("app.blitztext_linux.QMessageBox"):
        SettingsDialog._open_config_file(fake)

    (url_arg,) = m_open.call_args.args
    assert url_arg.toLocalFile() == str(fake.config.config_file)


def test_open_config_does_not_resave_existing_file_without_legacy_key(tmp_path):
    fake = _fake_self(tmp_path / ".config" / "blitztext-linux")
    fake.config.save()

    with patch.object(type(fake.config), "save") as m_save, \
            patch("app.blitztext_linux.QDesktopServices.openUrl", return_value=True), \
            patch("app.blitztext_linux.QMessageBox"):
        SettingsDialog._open_config_file(fake)

    m_save.assert_not_called()


def test_open_config_resaves_existing_legacy_config_before_open(tmp_path):
    config_dir = tmp_path / ".config" / "blitztext-linux"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.json"
    config_path.write_text(json.dumps({"openai_api_key": "legacy-placeholder"}), encoding="utf-8")
    fake = _fake_self(config_dir)
    assert fake.config.has_legacy_openai_api_key is True

    with patch("app.blitztext_linux.QDesktopServices.openUrl", return_value=True), \
            patch("app.blitztext_linux.QMessageBox"):
        SettingsDialog._open_config_file(fake)

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert "openai_api_key" not in saved
    assert saved["openai_api_key_env"] == "OPENAI_API_KEY"


def test_open_config_handles_save_error_before_open(tmp_path):
    fake = _fake_self(tmp_path / ".config" / "blitztext-linux")

    with patch.object(type(fake.config), "save", side_effect=OSError("disk full")), \
            patch("app.blitztext_linux.QDesktopServices.openUrl") as m_open, \
            patch("app.blitztext_linux.QMessageBox") as m_box:
        SettingsDialog._open_config_file(fake)

    m_open.assert_not_called()
    m_box.critical.assert_called_once()
    m_box.warning.assert_not_called()


def test_open_config_handles_open_failure(tmp_path):
    fake = _fake_self(tmp_path / ".config" / "blitztext-linux")

    with patch("app.blitztext_linux.QDesktopServices.openUrl", return_value=False) as m_open, \
            patch("app.blitztext_linux.QMessageBox") as m_box:
        SettingsDialog._open_config_file(fake)

    m_open.assert_called_once()
    m_box.warning.assert_called_once()
    m_box.critical.assert_not_called()


def test_refresh_api_key_status_shows_env_name_not_secret(monkeypatch):
    secret_value = "dummy-openai-key"
    monkeypatch.setenv("CUSTOM_OPENAI_KEY", secret_value)

    class FakeLineEdit:
        def text(self):
            return "CUSTOM_OPENAI_KEY"

    class FakeLabel:
        def __init__(self):
            self.text = ""

        def setText(self, value):
            self.text = value

    fake = SimpleNamespace(
        edit_api_key_env=FakeLineEdit(),
        config=SimpleNamespace(openai_api_key_env="OPENAI_API_KEY"),
        lbl_api_key_status=FakeLabel(),
    )

    SettingsDialog._refresh_api_key_status(fake)

    assert "CUSTOM_OPENAI_KEY" in fake.lbl_api_key_status.text
    assert "gesetzt" in fake.lbl_api_key_status.text
    assert secret_value not in fake.lbl_api_key_status.text

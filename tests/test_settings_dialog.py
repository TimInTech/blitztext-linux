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


class _Combo:
    def __init__(self, text="", data=None):
        self._text = text
        self._data = data

    def currentText(self):
        return self._text

    def currentData(self):
        return self._data


class _Edit:
    def __init__(self, text=""):
        self._text = text
        self.enabled = True

    def text(self):
        return self._text

    def toPlainText(self):
        return self._text

    def setText(self, value):
        self._text = value

    def setEnabled(self, value):
        self.enabled = bool(value)


class _Check:
    def __init__(self, checked=True):
        self._checked = checked

    def isChecked(self):
        return self._checked


def _fake_save_self(config_dir, preset_key):
    config = BlitztextConfig(config_dir=config_dir)
    return SimpleNamespace(
        config=config,
        combo_model=_Combo("base"),
        combo_backend=_Combo("openai-whisper"),
        edit_language=_Edit("de"),
        edit_audio_device=_Edit("@DEFAULT_SOURCE@"),
        combo_hotkey_mode=_Combo("hold"),
        combo_transcription_key=_Combo("KEY_LEFTALT"),
        edit_api_key_env=_Edit("OPENAI_API_KEY"),
        combo_llm_provider=_Combo(text="OpenRouter", data="openrouter"),
        edit_base_url=_Edit("https://openrouter.ai/api/v1"),
        edit_llm_model=_Edit("openai/gpt-4o"),
        combo_tone=_Combo("neutral"),
        combo_writing_preset=_Combo(text="E-Mail – formell", data=preset_key),
        combo_emoji=_Combo("mittel"),
        edit_dampf_prompt=_Edit(""),
        _collect_custom_terms=lambda: [],
        check_autopaste=_Check(True),
        edit_notes_folder=_Edit(""),
        spin_history_size=_Combo("50"),
        accept=lambda: None,
    )


def test_save_settings_persists_writing_preset(tmp_path):
    config_dir = tmp_path / ".config" / "blitztext-linux"
    fake = _fake_save_self(config_dir, "email_formal")

    SettingsDialog.save_settings(fake)

    assert fake.config.writing_preset == "email_formal"
    reloaded = BlitztextConfig(config_dir=config_dir)
    assert reloaded.writing_preset == "email_formal"


def test_save_settings_persists_llm_provider_fields(tmp_path):
    config_dir = tmp_path / ".config" / "blitztext-linux"
    fake = _fake_save_self(config_dir, "standard")

    SettingsDialog.save_settings(fake)

    reloaded = BlitztextConfig(config_dir=config_dir)
    assert reloaded.llm_provider == "openrouter"
    assert reloaded.llm_base_url == "https://openrouter.ai/api/v1"
    assert reloaded.llm_model == "openai/gpt-4o"


def test_build_llm_service_includes_base_url_and_model(tmp_path):
    # Regression: beide Konstruktionsorte (Init + Settings-Save) gehen ueber
    # _build_llm_service, damit base_url/model nicht an einer Stelle fehlen.
    from app.blitztext_linux import BlitztextApp

    config_dir = tmp_path / ".config" / "blitztext-linux"
    config = BlitztextConfig(config_dir=config_dir)
    config.llm_provider = "openrouter"
    config.llm_base_url = "https://openrouter.ai/api/v1"
    config.llm_model = "openai/gpt-4o"
    fake = SimpleNamespace(config=config)

    service = BlitztextApp._build_llm_service(fake)

    assert service.base_url == "https://openrouter.ai/api/v1"
    assert service.model == "openai/gpt-4o"


def test_provider_change_prefills_openrouter_base_url():
    fake = SimpleNamespace(
        combo_llm_provider=_Combo(text="OpenRouter", data="openrouter"),
        edit_base_url=_Edit(""),
    )
    SettingsDialog._on_llm_provider_changed(fake)
    assert fake.edit_base_url.text() == "https://openrouter.ai/api/v1"


def test_provider_change_to_openai_clears_and_disables_base_url():
    fake = SimpleNamespace(
        combo_llm_provider=_Combo(text="OpenAI", data="openai"),
        edit_base_url=_Edit("https://openrouter.ai/api/v1"),
    )
    SettingsDialog._on_llm_provider_changed(fake)
    assert fake.edit_base_url.text() == ""
    assert fake.edit_base_url.enabled is False


def test_provider_change_does_not_overwrite_existing_base_url():
    fake = SimpleNamespace(
        combo_llm_provider=_Combo(text="OpenRouter", data="openrouter"),
        edit_base_url=_Edit("https://my-proxy/api/v1"),
    )
    SettingsDialog._on_llm_provider_changed(fake)
    assert fake.edit_base_url.text() == "https://my-proxy/api/v1"


def test_save_settings_keeps_standard_preset(tmp_path):
    config_dir = tmp_path / ".config" / "blitztext-linux"
    fake = _fake_save_self(config_dir, "standard")

    SettingsDialog.save_settings(fake)

    assert fake.config.writing_preset == "standard"


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

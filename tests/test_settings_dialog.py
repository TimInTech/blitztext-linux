"""Tests für SettingsDialog-Helfer ohne echten Editor oder GUI-Leaks."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.blitztext_linux import SettingsDialog
from app.config import BlitztextConfig
from app.i18n import DEFAULT_LANGUAGE, get_language, set_language


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


def _fake_save_self(config_dir, preset_key, ui_language="de"):
    config = BlitztextConfig(config_dir=config_dir)
    return SimpleNamespace(
        config=config,
        combo_model=_Combo("base"),
        combo_backend=_Combo("openai-whisper"),
        edit_language=_Edit("de"),
        edit_audio_device=_Edit("@DEFAULT_SOURCE@"),
        combo_hotkey_mode=_Combo("hold"),
        combo_transcription_key=_Combo("KEY_LEFTALT"),
        edit_api_key_env=_Edit("OPENROUTER_API_KEY"),
        combo_llm_provider=_Combo(text="OpenRouter", data="openrouter"),
        edit_base_url=_Edit("https://openrouter.ai/api/v1"),
        edit_llm_model=_Edit("openai/gpt-4o"),
        combo_tone=_Combo(text="neutral", data="neutral"),
        combo_writing_preset=_Combo(text="E-Mail – formell", data=preset_key),
        edit_compose_custom_preset=_Edit(""),
        combo_emoji=_Combo("mittel", "mittel"),
        edit_dampf_prompt=_Edit(""),
        _collect_custom_terms=lambda: [],
        check_autopaste=_Check(True),
        edit_notes_folder=_Edit(""),
        spin_history_size=_Combo("50"),
        combo_ui_language=_Combo(
            text="English" if ui_language == "en" else "Deutsch",
            data=ui_language,
        ),
        edit_compose_signature=_Edit(""),
        check_compose_signature_auto_append=_Check(False),
        accept=lambda: None,
    )


def test_save_settings_persists_writing_preset(tmp_path):
    config_dir = tmp_path / ".config" / "blitztext-linux"
    fake = _fake_save_self(config_dir, "email_formal")

    SettingsDialog.save_settings(fake)

    assert fake.config.writing_preset == "change_tone"
    assert fake.config.text_improver_tone == "formal"
    reloaded = BlitztextConfig(config_dir=config_dir)
    assert reloaded.writing_preset == "change_tone"
    assert reloaded.text_improver_tone == "formal"


def test_save_settings_persists_llm_provider_fields(tmp_path):
    config_dir = tmp_path / ".config" / "blitztext-linux"
    fake = _fake_save_self(config_dir, "standard")

    SettingsDialog.save_settings(fake)

    reloaded = BlitztextConfig(config_dir=config_dir)
    assert reloaded.llm_provider == "openrouter"
    assert reloaded.llm_base_url == "https://openrouter.ai/api/v1"
    assert reloaded.llm_model == "openai/gpt-4o"


def test_save_settings_rejects_public_http_base_url_without_saving_or_accepting(tmp_path):
    config_dir = tmp_path / ".config" / "blitztext-linux"
    fake = _fake_save_self(config_dir, "standard")
    fake.edit_base_url = _Edit("http://api.example.com/v1")
    fake.accept = Mock()

    with patch("app.blitztext_linux.QMessageBox") as message_box:
        SettingsDialog.save_settings(fake)

    message_box.critical.assert_called_once()
    fake.accept.assert_not_called()
    assert not fake.config.config_file.exists()


def test_save_settings_rejects_empty_non_openai_endpoint_without_mutating_config(tmp_path):
    config_dir = tmp_path / ".config" / "blitztext-linux"
    fake = _fake_save_self(config_dir, "standard")
    fake.combo_llm_provider = _Combo(text="Eigener Endpunkt", data="custom")
    fake.edit_base_url = _Edit("")
    fake.edit_api_key_env = _Edit("CUSTOM_LLM_API_KEY")
    fake.accept = Mock()

    with patch("app.blitztext_linux.QMessageBox") as message_box:
        SettingsDialog.save_settings(fake)

    message_box.critical.assert_called_once()
    fake.accept.assert_not_called()
    assert fake.config.llm_provider == "openai"
    assert fake.config.llm_base_url == ""
    assert not fake.config.config_file.exists()


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "https://0177.0.0.1/v1",
        "https://999.1.1.1/v1",
        "https://api.example.com/\x7f",
        "https://api.example.com/\u0080",
    ],
)
def test_save_settings_rejects_invalid_https_url_without_saving_or_accepting(tmp_path, unsafe_url):
    config_dir = tmp_path / ".config" / "blitztext-linux"
    fake = _fake_save_self(config_dir, "standard")
    fake.edit_base_url = _Edit(unsafe_url)
    fake.accept = Mock()

    with patch("app.blitztext_linux.QMessageBox") as message_box:
        SettingsDialog.save_settings(fake)

    message_box.critical.assert_called_once()
    fake.accept.assert_not_called()
    assert not fake.config.config_file.exists()


def test_save_settings_persists_ui_language_for_the_next_start(tmp_path):
    config_dir = tmp_path / ".config" / "blitztext-linux"
    fake = _fake_save_self(config_dir, "standard", ui_language="en")

    try:
        set_language("de")
        SettingsDialog.save_settings(fake)

        reloaded = BlitztextConfig(config_dir=config_dir)
        assert reloaded.ui_language == "en"
        assert get_language() == "de"
    finally:
        set_language(DEFAULT_LANGUAGE)


def test_app_init_applies_configured_ui_language(tmp_path):
    from app.blitztext_linux import BlitztextApp

    config = BlitztextConfig(config_dir=tmp_path / ".config" / "blitztext-linux")
    config.ui_language = "en"
    config.paste_key_delay_ms = 135
    fake_qapp = Mock()

    try:
        set_language("de")
        with patch("app.blitztext_linux.Config.load", return_value=config), \
                patch.object(BlitztextApp, "setup_tray"), \
                patch.object(BlitztextApp, "start_hotkey_worker"), \
                patch("app.blitztext_linux.AudioRecorder"), \
                patch("app.blitztext_linux.PasteService") as paste_service_cls:
            BlitztextApp(fake_qapp)

        assert get_language() == "en"
        paste_service_cls.assert_called_once_with(autopaste=config.autopaste, key_delay_ms=135)
    finally:
        set_language(DEFAULT_LANGUAGE)


def test_refresh_i18n_texts_updates_existing_shell():
    from app.blitztext_linux import BlitztextApp

    fake = SimpleNamespace(
        app=Mock(),
        action_settings=Mock(),
        action_quit=Mock(),
        _main_window=Mock(),
        update_tray_state=Mock(),
    )

    try:
        set_language("en")
        BlitztextApp._refresh_i18n_texts(fake)

        fake.action_settings.setText.assert_called_once_with("Settings…")
        fake.action_quit.setText.assert_called_once_with("Quit")
        fake._main_window.setWindowTitle.assert_called_once_with("Blitztext")
        fake.update_tray_state.assert_called_once()
    finally:
        set_language(DEFAULT_LANGUAGE)


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


def test_build_llm_service_ignores_base_url_when_provider_is_openai(tmp_path):
    # Provider ist autoritativ: bei "openai" darf eine (z. B. manuell in config.json
    # gesetzte) base_url NICHT verwendet werden -> OpenAI-Standardendpunkt.
    from app.blitztext_linux import BlitztextApp

    config_dir = tmp_path / ".config" / "blitztext-linux"
    config = BlitztextConfig(config_dir=config_dir)
    config.llm_provider = "openai"
    config.llm_base_url = "https://openrouter.ai/api/v1"
    config.llm_model = "gpt-4o"
    fake = SimpleNamespace(config=config)

    service = BlitztextApp._build_llm_service(fake)

    assert service.base_url == ""
    assert service.model == "gpt-4o"


@pytest.mark.parametrize(
    ("language", "expected_notice"),
    [
        ("de", "Eine unsichere HTTP-Basis-URL aus der Konfiguration wurde entfernt. Verwende für öffentliche Endpunkte HTTPS."),
        ("en", "An unsafe HTTP base URL from the configuration was removed. Use HTTPS for public endpoints."),
    ],
)
def test_migrated_unsafe_base_url_shows_bilingual_notice_and_uses_empty_service_url(
    tmp_path, language, expected_notice, monkeypatch
):
    from PyQt6.QtWidgets import QApplication
    from app.blitztext_linux import BlitztextApp

    qapp = QApplication.instance() or QApplication([])
    config_dir = tmp_path / ".config" / "blitztext-linux"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.json").write_text(
        json.dumps({"llm_provider": "custom", "llm_base_url": "http://api.example.com/v1"}),
        encoding="utf-8",
    )

    try:
        monkeypatch.setenv("OPENAI_API_KEY", "openai-key-must-not-leave-the-app")
        set_language(language)
        config = BlitztextConfig(config_dir=config_dir)
        dialog = SettingsDialog(config)
        service = BlitztextApp._build_llm_service(SimpleNamespace(config=config))

        assert config.has_unsafe_llm_base_url is True
        assert dialog.lbl_unsafe_llm_base_url_notice is not None
        assert dialog.lbl_unsafe_llm_base_url_notice.text() == expected_notice
        assert service.base_url == ""
        assert service.api_key == ""
    finally:
        dialog.close()
        qapp.processEvents()
        set_language(DEFAULT_LANGUAGE)


def test_provider_change_prefills_openrouter_base_url():
    fake = SimpleNamespace(
        combo_llm_provider=_Combo(text="OpenRouter", data="openrouter"),
        edit_base_url=_Edit(""),
        edit_api_key_env=_Edit("OPENAI_API_KEY"),
    )
    SettingsDialog._on_llm_provider_changed(fake)
    assert fake.edit_base_url.text() == "https://openrouter.ai/api/v1"
    assert fake.edit_api_key_env.text() == "OPENROUTER_API_KEY"


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


def test_save_settings_persists_tone_via_data(tmp_path):
    config_dir = tmp_path / ".config" / "blitztext-linux"
    fake = _fake_save_self(config_dir, "standard")
    # Anzeige "professionell" → interner Wert "formal" (currentData).
    fake.combo_tone = _Combo(text="professionell", data="formal")

    SettingsDialog.save_settings(fake)

    assert fake.config.text_improver_tone == "formal"
    reloaded = BlitztextConfig(config_dir=config_dir)
    assert reloaded.text_improver_tone == "formal"


def test_save_settings_persists_compose_custom_preset(tmp_path):
    config_dir = tmp_path / ".config" / "blitztext-linux"
    fake = _fake_save_self(config_dir, "standard")
    fake.edit_compose_custom_preset = _Edit("Freier Compose-Prompt.")

    SettingsDialog.save_settings(fake)

    assert fake.config.compose_custom_preset_text == "Freier Compose-Prompt."
    reloaded = BlitztextConfig(config_dir=config_dir)
    assert reloaded.compose_custom_preset_text == "Freier Compose-Prompt."


@pytest.mark.parametrize(
    ("language", "expected_status"),
    [("de", "gesetzt"), ("en", "set")],
)
def test_refresh_api_key_status_shows_env_name_not_secret(
    monkeypatch, language, expected_status
):
    secret_value = "dummy-openai-key"
    monkeypatch.setenv("CUSTOM_OPENAI_KEY", secret_value)
    set_language(language)

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

    try:
        with patch("app.blitztext_linux.theme.set_status_role") as set_status_role:
            SettingsDialog._refresh_api_key_status(fake)
    finally:
        set_language(DEFAULT_LANGUAGE)

    assert "CUSTOM_OPENAI_KEY" in fake.lbl_api_key_status.text
    assert expected_status in fake.lbl_api_key_status.text
    assert secret_value not in fake.lbl_api_key_status.text
    set_status_role.assert_called_once_with(fake.lbl_api_key_status, "success")

# --- Goal 04: Settings nutzt dieselbe Auswahl und bestehende Prompt-Ablage --


def test_goal_settings_lists_only_core_actions_and_keeps_single_custom_prompt_field(tmp_path):
    from PyQt6.QtWidgets import QApplication
    from app.writing_presets import WRITING_PRESET_KEYS

    qapp = QApplication.instance() or QApplication([])
    config = BlitztextConfig(config_dir=tmp_path / ".config" / "blitztext-linux")
    config.writing_preset = "custom"
    config.compose_custom_preset_text = "Bestehender Nutzer-Prompt."
    dialog = SettingsDialog(config)
    try:
        values = tuple(
            dialog.combo_writing_preset.itemData(index)
            for index in range(dialog.combo_writing_preset.count())
            if isinstance(dialog.combo_writing_preset.itemData(index), str)
        )
        assert values == WRITING_PRESET_KEYS == (
            "standard", "shorten", "expand", "change_tone", "custom"
        )
        assert dialog.combo_writing_preset.currentData() == "custom"
        assert dialog.edit_compose_custom_preset.toPlainText() == "Bestehender Nutzer-Prompt."
    finally:
        dialog.close()
        qapp.processEvents()


def test_goal_settings_save_preserves_custom_selection_and_prompt(tmp_path):
    config_dir = tmp_path / ".config" / "blitztext-linux"
    fake = _fake_save_self(config_dir, "custom")
    fake.edit_compose_custom_preset = _Edit("  Nutzer-Prompt exakt.  \n")

    SettingsDialog.save_settings(fake)
    reloaded = BlitztextConfig(config_dir=config_dir)

    assert reloaded.writing_preset == "custom"
    assert reloaded.compose_custom_preset_text == "  Nutzer-Prompt exakt.  \n"


def test_settings_dialog_attaches_help_to_layout_fields_and_editors(tmp_path):
    from PyQt6.QtWidgets import QApplication
    from app.i18n import t

    qapp = QApplication.instance() or QApplication([])
    config = BlitztextConfig(config_dir=tmp_path / ".config" / "blitztext-linux")
    dialog = SettingsDialog(config)
    try:
        # Base URL is in a QVBoxLayout; ensure the QLineEdit receives help/accessible description
        assert dialog.edit_base_url.toolTip() == t("settings.base_url.help")
        assert dialog.edit_base_url.accessibleDescription() == t("settings.base_url.help")

        # Counter-check: a field mounted directly as a widget keeps working too.
        assert dialog.edit_llm_model.toolTip() == t("settings.llm_model.help")
        assert dialog.edit_llm_model.accessibleDescription() == t("settings.llm_model.help")
    finally:
        dialog.close()
        qapp.processEvents()

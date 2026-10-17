"""Tests für das Tray-Submenu „Schreibstil-Vorlage" (Paket F) und die
bidirektionale Sync Tray ↔ Hauptfenster (Paket K).

Deckt das Zusammenspiel von Preset-Auswahl im Tray, Config-Persistenz und
LLM-Service-Neuaufbau ab:

* Auswahl im Submenu persistiert den Preset und baut den LLMService neu.
* Das Menü spiegelt jederzeit die ``config.writing_preset`` (Häkchen).
* Ein Settings-Save mit geändertem Preset gleicht das Häkchen wieder an.
* Tray-Auswahl spiegelt sich im Hauptfenster-Combo (und umgekehrt).

GUI-gated über ``WHISPER_GUI_TESTS=1``: die echte ``BlitztextApp`` baut Tray +
QActionGroup auf und benötigt eine (Offscreen-)QApplication, analog zu
``tests/test_state_machine.py``.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.config import BlitztextConfig
from app.writing_presets import DEFAULT_PRESET_KEY, WRITING_PRESET_KEYS

_GUI = os.environ.get("WHISPER_GUI_TESTS") == "1"
gui_only = pytest.mark.skipif(not _GUI, reason="benötigt WHISPER_GUI_TESTS=1 (Display)")


@pytest.fixture
def tray_app(tmp_path):
    """Echte App mit isolierter Config (tmp), ohne evdev-Thread.

    Die Config wird nach dem Boot auf ein tmp-Verzeichnis umgehängt, damit der
    Handler ``config.save()`` nie in die echte User-Config schreibt. Das
    Preset-Menü wird danach neu synchronisiert.
    """
    from PyQt6.QtWidgets import QApplication
    from app.blitztext_linux import BlitztextApp

    qapp = QApplication.instance() or QApplication([])
    app = BlitztextApp(qapp)
    app.stop_hotkey_worker()  # kein echter evdev-Thread im Test

    app.config = BlitztextConfig(config_dir=tmp_path / ".config" / "blitztext-linux")
    app._refresh_preset_menu()
    yield app
    app.stop_hotkey_worker()


def _other_key(current: str) -> str:
    """Liefert einen vom aktuellen verschiedenen, gültigen Preset-Schlüssel."""
    return next(k for k in WRITING_PRESET_KEYS if k != current)


@gui_only
class TestPresetMenu:
    def test_saved_compose_instruction_rebuilds_shared_service(self, tray_app):
        main = tray_app._ensure_main_window()
        window = tray_app._ensure_compose_window()
        window.edit_custom_prompt()
        window.txtOwnPrompt.setPlainText("Keep every fact. Use short sentences.")
        window.btnSavePrompt.click()
        assert tray_app.llm_service.writing_custom_prompt == "Keep every fact. Use short sentences."
        assert window._llm_service is tray_app.llm_service
        assert tray_app.config.writing_preset == "custom"
        assert tray_app.llm_service.writing_preset == "custom"
        assert tray_app.preset_actions["custom"].isChecked()
        assert main._preset_combo.currentData() == "custom"
        assert BlitztextConfig(config_dir=tray_app.config.config_dir).compose_custom_preset_text == "Keep every fact. Use short sentences."
        window.close()

    def test_handler_persists_and_rebuilds_service(self, tray_app):
        """Auswahl im Tray: Config gesetzt + gespeichert + Service neu gebaut."""
        target = _other_key(tray_app.config.writing_preset)
        old_service = tray_app.llm_service

        tray_app._on_writing_preset_selected(target)

        assert tray_app.config.writing_preset == target
        # Auf Platte persistiert: frische Instanz liest denselben Preset.
        reloaded = BlitztextConfig(config_dir=tray_app.config.config_dir)
        assert reloaded.writing_preset == target
        # Service wurde neu konstruiert.
        assert tray_app.llm_service is not old_service

    def test_handler_noop_when_same_preset(self, tray_app):
        """Erneute Auswahl des aktiven Presets schreibt nicht erneut (No-Op)."""
        current = tray_app.config.writing_preset
        old_service = tray_app.llm_service

        tray_app._on_writing_preset_selected(current)

        assert tray_app.config.writing_preset == current
        assert tray_app.llm_service is old_service
        # Kein Disk-Write erfolgt -> keine Config-Datei angelegt.
        assert not tray_app.config.config_file.is_file()

    def test_handler_reverts_selection_when_preset_save_fails(self, tray_app):
        original = tray_app.config.writing_preset
        target = _other_key(original)
        tray_app.preset_actions[target].setChecked(True)
        old_service = tray_app.llm_service

        with patch.object(tray_app.config, "save", side_effect=OSError("disk full")), \
             patch.object(tray_app, "show_tray_error") as tray_error:
            tray_app._on_writing_preset_selected(target)

        assert tray_app.config.writing_preset == original
        assert tray_app.preset_actions[original].isChecked() is True
        assert tray_app.llm_service is old_service
        tray_error.assert_called_once()

    def test_menu_mirrors_config(self, tray_app):
        """Das Häkchen folgt der Config nach ``_refresh_preset_menu``."""
        target = _other_key(tray_app.config.writing_preset)
        tray_app.config.writing_preset = target

        tray_app._refresh_preset_menu()

        assert tray_app.preset_actions[target].isChecked() is True
        for key, action in tray_app.preset_actions.items():
            if key != target:
                assert action.isChecked() is False

    def test_refresh_falls_back_to_standard_for_unknown(self, tray_app):
        """Ein nicht im Menü vorhandener Wert wählt den Standard-Preset."""
        # Direkter Eingriff am Backing-Store umgeht die Setter-Validierung,
        # um einen "verwaisten" Config-Wert zu simulieren.
        tray_app.config._data["workflows"]["writing_preset"] = "gibt_es_nicht"

        tray_app._refresh_preset_menu()

        assert tray_app.preset_actions[DEFAULT_PRESET_KEY].isChecked() is True

    def test_settings_save_updates_check(self, tray_app, monkeypatch):
        """Settings-Save mit geändertem Preset gleicht das Häkchen an."""
        from PyQt6.QtWidgets import QDialog
        import app.blitztext_linux as mod

        target = _other_key(tray_app.config.writing_preset)

        class _FakeDialog:
            def __init__(self, config):
                # Dialog "speichert" den neuen Preset in dieselbe Config.
                config.writing_preset = target

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(mod, "SettingsDialog", _FakeDialog)

        tray_app.show_settings_dialog()

        assert tray_app.preset_actions[target].isChecked() is True

    def test_submenu_disabled_when_llm_unavailable(self, tray_app, monkeypatch):
        """Ohne nutzbaren LLM-Dienst wird das Preset-Submenu deaktiviert."""
        monkeypatch.setattr(tray_app.llm_service, "is_available", lambda: False)

        tray_app.update_menu_availability()

        assert tray_app.menu_preset.isEnabled() is False

    def test_submenu_enabled_when_llm_available(self, tray_app, monkeypatch):
        """Mit nutzbarem LLM-Dienst ist das Preset-Submenu auswählbar."""
        monkeypatch.setattr(tray_app.llm_service, "is_available", lambda: True)

        tray_app.update_menu_availability()

        assert tray_app.menu_preset.isEnabled() is True


@gui_only
class TestMainWindowPresetSync:
    """Bidirektionale Sync Tray ↔ Hauptfenster-Preset-Combo (Paket K)."""

    def _open_window(self, tray_app):
        """Öffnet das Hauptfenster und gibt es zurück."""
        tray_app.show_main_window()
        return tray_app._main_window

    def test_window_init_syncs_config_preset(self, tray_app):
        """Beim Öffnen spiegelt der Combo den gespeicherten Preset."""
        target = _other_key(tray_app.config.writing_preset)
        tray_app.config.writing_preset = target

        window = self._open_window(tray_app)

        assert window._preset_combo.currentData() == target

    def test_tray_change_updates_main_window(self, tray_app):
        """Tray-Auswahl aktualisiert den Preset-Combo im Hauptfenster."""
        window = self._open_window(tray_app)
        target = _other_key(tray_app.config.writing_preset)

        tray_app._on_writing_preset_selected(target)

        assert window._preset_combo.currentData() == target

    def test_main_window_change_updates_tray(self, tray_app):
        """Preset-Änderung im Hauptfenster setzt das Tray-Häkchen."""
        self._open_window(tray_app)
        target = _other_key(tray_app.config.writing_preset)

        tray_app.main_window_preset_changed(target)

        assert tray_app.preset_actions[target].isChecked() is True
        assert tray_app.config.writing_preset == target

    def test_main_window_change_noop_on_same_preset(self, tray_app):
        """Erneutes Setzen desselben Presets aus dem Hauptfenster ist No-Op."""
        self._open_window(tray_app)
        current = tray_app.config.writing_preset
        old_service = tray_app.llm_service

        tray_app.main_window_preset_changed(current)

        assert tray_app.llm_service is old_service
        assert not tray_app.config.config_file.is_file()

    def test_settings_save_syncs_main_window_combo(self, tray_app, monkeypatch):
        """Settings-Save mit geändertem Preset gleicht auch den Combo an."""
        from PyQt6.QtWidgets import QDialog
        import app.blitztext_linux as mod

        window = self._open_window(tray_app)
        target = _other_key(tray_app.config.writing_preset)

        class _FakeDialog:
            def __init__(self, config):
                config.writing_preset = target

            def exec(self):
                return QDialog.DialogCode.Accepted

        monkeypatch.setattr(mod, "SettingsDialog", _FakeDialog)
        tray_app.show_settings_dialog()

        assert window._preset_combo.currentData() == target

    def test_preset_combo_is_only_shown_where_it_acts(self, tray_app):
        """The style only exists for text improvement; elsewhere the field is gone."""
        from app.workflows import WorkflowType

        window = self._open_window(tray_app)
        window._btn_options.click()

        for i in range(window._workflow_combo.count()):
            wf = window._workflow_combo.itemData(i)
            window._workflow_combo.setCurrentIndex(i)
            assert window._preset_combo.isVisible() == (wf == WorkflowType.TEXT_IMPROVER), wf
        window._options_popup.hide()

# --- Goal 04: Tray und Hauptfenster zeigen dieselben Kernaktionen -----------

GOAL_VISIBLE_ACTIONS = ("standard", "shorten", "expand", "change_tone", "custom")


@gui_only
def test_goal_tray_and_main_window_share_reduced_action_catalog(tray_app):
    assert tuple(tray_app.preset_actions) == GOAL_VISIBLE_ACTIONS
    window = tray_app._ensure_main_window()
    main_values = tuple(
        window._preset_combo.itemData(index)
        for index in range(window._preset_combo.count())
        if isinstance(window._preset_combo.itemData(index), str)
    )
    assert main_values == GOAL_VISIBLE_ACTIONS


@gui_only
def test_goal_custom_action_persists_without_changing_custom_prompt(tray_app):
    tray_app.config.compose_custom_preset_text = "Vorhandener eigener Prompt."

    tray_app._on_writing_preset_selected("custom")

    reloaded = BlitztextConfig(config_dir=tray_app.config.config_dir)
    assert reloaded.writing_preset == "custom"
    assert reloaded.compose_custom_preset_text == "Vorhandener eigener Prompt."

# --- Goal 04: offenes Compose-Fenster erhält den aktuellen Service --------


@gui_only
def test_goal_tray_change_refreshes_service_in_open_compose(tray_app):
    compose = tray_app._ensure_compose_window()
    old_service = compose._llm_service
    target = _other_key(tray_app.config.writing_preset)

    tray_app._on_writing_preset_selected(target)

    assert tray_app.llm_service is not old_service
    assert compose._llm_service is tray_app.llm_service


@gui_only
def test_goal_main_window_change_refreshes_service_in_open_compose(tray_app):
    compose = tray_app._ensure_compose_window()
    old_service = compose._llm_service
    target = _other_key(tray_app.config.writing_preset)

    tray_app.main_window_preset_changed(target)

    assert tray_app.llm_service is not old_service
    assert compose._llm_service is tray_app.llm_service


@gui_only
def test_goal_settings_rebuild_refreshes_service_in_open_compose(tray_app, monkeypatch):
    from PyQt6.QtWidgets import QDialog
    import app.blitztext_linux as mod

    compose = tray_app._ensure_compose_window()
    old_service = compose._llm_service

    class _AcceptedDialog:
        def __init__(self, _config):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(mod, "SettingsDialog", _AcceptedDialog)

    tray_app.show_settings_dialog()

    assert tray_app.llm_service is not old_service
    assert compose._llm_service is tray_app.llm_service


@gui_only
class TestModeSwitch:
    def test_provider_switch_needs_a_key_and_reverts_without_one(self, tray_app, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        main = tray_app._ensure_main_window()
        before = (tray_app.config.llm_provider, tray_app.config.llm_base_url)

        tray_app.main_window_provider_changed("openrouter")

        assert (tray_app.config.llm_provider, tray_app.config.llm_base_url) == before
        assert main._provider_combo.currentData() == before[0]

    def test_provider_switch_with_key_persists_and_rebuilds(self, tray_app, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-not-a-real-key")
        main = tray_app._ensure_main_window()
        old_service = tray_app.llm_service

        tray_app.main_window_provider_changed("openrouter")

        assert tray_app.config.llm_provider == "openrouter"
        assert tray_app.config.llm_base_url == "https://openrouter.ai/api/v1"
        assert tray_app.config.openai_api_key_env == "OPENROUTER_API_KEY"
        assert tray_app.llm_service is not old_service
        assert main._provider_combo.currentData() == "openrouter"
        on_disk = BlitztextConfig(config_dir=tray_app.config.config_dir)
        assert on_disk.llm_provider == "openrouter"

    def test_provider_switch_back_to_openai_restores_defaults(self, tray_app, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-not-a-real-key")
        monkeypatch.setenv("OPENAI_API_KEY", "dummy-not-a-real-key")
        tray_app.main_window_provider_changed("openrouter")
        tray_app.main_window_provider_changed("openai")

        assert tray_app.config.llm_provider == "openai"
        assert tray_app.config.llm_base_url == ""
        assert tray_app.config.openai_api_key_env == "OPENAI_API_KEY"

    def test_model_switch_persists_and_skips_noop(self, tray_app, monkeypatch):
        monkeypatch.setattr(tray_app, "_confirm_model_download", lambda model: True)
        tray_app.main_window_model_changed("tiny")
        assert tray_app.config.model == "tiny"
        assert BlitztextConfig(config_dir=tray_app.config.config_dir).model == "tiny"

    def test_heavy_model_switch_asks_first_and_can_be_declined(self, tray_app, monkeypatch):
        main = tray_app._ensure_main_window()
        tray_app.config.model = "base"
        asked = []
        monkeypatch.setattr(
            tray_app, "_confirm_model_download", lambda model: asked.append(model) or False
        )

        tray_app.main_window_model_changed("small")

        assert asked == ["small"]
        assert tray_app.config.model == "base"
        assert main._model_combo.currentData() == "base"


@gui_only
class TestModeSwitchHardening:
    def test_leaving_a_custom_endpoint_never_overwrites_it(self, tray_app, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-not-a-real-key")
        cfg = tray_app.config
        cfg.llm_provider = "custom"
        cfg.llm_base_url = "https://llm.example.org/v1"
        cfg.openai_api_key_env = "MY_CUSTOM_KEY"
        tray_app._ensure_main_window().set_llm_provider("custom")

        tray_app.main_window_provider_changed("openrouter")

        assert (cfg.llm_provider, cfg.llm_base_url, cfg.openai_api_key_env) == (
            "custom", "https://llm.example.org/v1", "MY_CUSTOM_KEY")
        assert tray_app._main_window._provider_combo.currentData() == "custom"

    def test_custom_is_not_a_target_of_the_quick_switch(self, tray_app, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "dummy-not-a-real-key")
        cfg = tray_app.config
        cfg.llm_provider = "openai"
        cfg.llm_base_url = "https://stale.example.org/v1"

        tray_app.main_window_provider_changed("custom")

        assert cfg.llm_provider == "openai"

    def test_custom_key_variable_survives_openai_openrouter_round_trip(self, tray_app, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-not-a-real-key")
        monkeypatch.setenv("WORK_OPENAI_KEY", "dummy-not-a-real-key")
        cfg = tray_app.config
        cfg.llm_provider = "openai"
        cfg.openai_api_key_env = "WORK_OPENAI_KEY"

        tray_app.main_window_provider_changed("openrouter")
        tray_app.main_window_provider_changed("openai")

        assert cfg.openai_api_key_env == "WORK_OPENAI_KEY"
        assert cfg.llm_base_url == ""

    def test_failed_provider_save_restores_state_and_combo(self, tray_app, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-not-a-real-key")
        main = tray_app._ensure_main_window()
        before = (tray_app.config.llm_provider, tray_app.config.llm_base_url,
                  tray_app.config.openai_api_key_env)
        monkeypatch.setattr(tray_app.config, "save", lambda: (_ for _ in ()).throw(OSError("disk full")))

        tray_app.main_window_provider_changed("openrouter")

        assert (tray_app.config.llm_provider, tray_app.config.llm_base_url,
                tray_app.config.openai_api_key_env) == before
        assert main._provider_combo.currentData() == before[0]

    def test_failed_model_save_restores_state_and_does_not_latch_an_error(self, tray_app, monkeypatch):
        main = tray_app._ensure_main_window()
        tray_app.config.model = "base"
        monkeypatch.setattr(tray_app.config, "save", lambda: (_ for _ in ()).throw(OSError("disk full")))

        tray_app.main_window_model_changed("tiny")

        assert tray_app.config.model == "base"
        assert main._model_combo.currentData() == "base"
        assert tray_app._tray_error_message in (None, "")

    def test_unchanged_model_is_a_noop(self, tray_app, monkeypatch):
        tray_app.config.model = "base"
        calls = []
        monkeypatch.setattr(tray_app.config, "save", lambda: calls.append(1))
        monkeypatch.setattr(tray_app, "_confirm_model_download", lambda m: calls.append("ask") or True)

        tray_app.main_window_model_changed("base")

        assert calls == []

    def test_model_prompt_closes_the_popup_first(self, tray_app, monkeypatch):
        main = tray_app._ensure_main_window()
        main._show_options_popup()
        seen = []
        from PyQt6.QtWidgets import QMessageBox
        monkeypatch.setattr(
            QMessageBox, "question",
            staticmethod(lambda *a, **k: seen.append(main._options_popup.isVisible()) or QMessageBox.StandardButton.No),
        )

        tray_app.main_window_model_changed("small")

        assert seen == [False]


@gui_only
class TestAiGate:
    """The missing-key check lives in _start_recording, so GUI and hotkeys behave alike."""

    @pytest.fixture
    def recorder(self, tray_app, monkeypatch):
        from unittest.mock import MagicMock

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        tray_app.config._legacy_openai_api_key_value = ""
        tray_app._rebuild_llm_service()
        warnings = []
        monkeypatch.setattr(tray_app, "show_tray_warning", lambda *a: warnings.append(a))
        tray_app.audio_recorder = MagicMock()
        tray_app.warnings = warnings
        return tray_app.audio_recorder

    def test_gui_ai_recording_without_a_key_never_starts_audio(self, tray_app, recorder):
        from app.workflows import WorkflowType

        tray_app.gui_toggle_recording(WorkflowType.TEXT_IMPROVER)

        recorder.start.assert_not_called()
        assert tray_app.state == "IDLE"
        assert len(tray_app.warnings) == 1

    def test_hotkey_ai_recording_without_a_key_never_starts_audio(self, tray_app, recorder):
        from app.workflows import WorkflowType

        for workflow in (WorkflowType.TEXT_IMPROVER, WorkflowType.DAMPF_ABLASSEN, WorkflowType.EMOJI_TEXT):
            tray_app._on_workflow_triggered(workflow)

        recorder.start.assert_not_called()
        assert tray_app.state == "IDLE"
        assert len(tray_app.warnings) == 3

    def test_refusal_says_no_recording_started_not_provider_unchanged(self, tray_app, recorder):
        from app.i18n import t
        from app.workflows import WorkflowType

        tray_app.gui_toggle_recording(WorkflowType.TEXT_IMPROVER)

        title, message = tray_app.warnings[0]
        assert title == t("mainwindow.provider.no_key.title")
        assert tray_app.config.openai_api_key_env in message
        assert message == t("mainwindow.recording.no_key.message").format(
            env=tray_app.config.openai_api_key_env)
        assert "provider" not in message.lower()

    def test_local_workflow_starts_without_a_key(self, tray_app, recorder):
        from app.workflows import WorkflowType

        tray_app.gui_toggle_recording(WorkflowType.TRANSCRIPTION)

        recorder.start.assert_called_once()
        assert tray_app.state == "RECORDING"
        assert tray_app.warnings == []

    def test_compose_voice_routing_records_ai_workflow_without_a_key(self, tray_app, recorder, monkeypatch):
        from app.workflows import WorkflowType

        monkeypatch.setattr(tray_app, "_compose_voice_routing_enabled", lambda: True)

        tray_app.gui_toggle_recording(WorkflowType.TEXT_IMPROVER)

        recorder.start.assert_called_once()
        assert tray_app.state == "RECORDING"
        assert tray_app._recording_routes_to_compose is True
        assert tray_app.warnings == []

    def test_compose_voice_routing_hotkey_records_without_a_key(self, tray_app, recorder, monkeypatch):
        from app.workflows import WorkflowType

        monkeypatch.setattr(tray_app, "_compose_voice_routing_enabled", lambda: True)

        tray_app._on_workflow_triggered(WorkflowType.EMOJI_TEXT)

        recorder.start.assert_called_once()
        assert tray_app.state == "RECORDING"

    def test_ai_recording_with_a_key_starts(self, tray_app, recorder, monkeypatch):
        from app.workflows import WorkflowType

        monkeypatch.setenv("OPENAI_API_KEY", "dummy-not-a-real-key")
        tray_app._rebuild_llm_service()

        tray_app.gui_toggle_recording(WorkflowType.TEXT_IMPROVER)

        recorder.start.assert_called_once()
        assert tray_app.state == "RECORDING"
        assert tray_app.warnings == []


@gui_only
class TestProviderKeyMemo:
    def test_personal_openai_variable_survives_a_restart(self, tray_app, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-not-a-real-key")
        monkeypatch.setenv("WORK_OPENAI_KEY", "dummy-not-a-real-key")
        cfg = tray_app.config
        cfg.llm_provider = "openai"
        cfg.openai_api_key_env = "WORK_OPENAI_KEY"

        tray_app.main_window_provider_changed("openrouter")
        tray_app.config = BlitztextConfig(config_dir=cfg.config_dir)  # restart
        tray_app.main_window_provider_changed("openai")

        assert tray_app.config.openai_api_key_env == "WORK_OPENAI_KEY"
        assert tray_app.config.openai_provider_key_env == ""

    def test_memo_stores_a_variable_name_never_a_key_value(self, tray_app, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-not-a-real-key")
        monkeypatch.setenv("OPENAI_API_KEY", "dummy-secret-value-123")
        tray_app.main_window_provider_changed("openrouter")

        raw = (tray_app.config.config_dir / "config.json").read_text(encoding="utf-8")

        assert "dummy-secret-value-123" not in raw
        assert "dummy-not-a-real-key" not in raw

    def test_failed_save_restores_the_memo(self, tray_app, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "dummy-not-a-real-key")
        cfg = tray_app.config
        cfg.openai_api_key_env = "WORK_OPENAI_KEY"
        monkeypatch.setattr(cfg, "save", lambda: (_ for _ in ()).throw(OSError("disk full")))

        tray_app.main_window_provider_changed("openrouter")

        assert cfg.openai_provider_key_env == ""
        assert cfg.openai_api_key_env == "WORK_OPENAI_KEY"
        assert cfg.llm_provider == "openai"

    def test_settings_dialog_parks_and_clears_the_memo(self, tray_app):
        from app.blitztext_linux import SettingsDialog

        cfg = tray_app.config
        cfg.openai_api_key_env = "WORK_OPENAI_KEY"
        dialog = SettingsDialog(cfg)
        dialog.combo_llm_provider.setCurrentIndex(dialog.combo_llm_provider.findData("openrouter"))
        dialog.edit_base_url.setText("https://openrouter.ai/api/v1")
        dialog.edit_api_key_env.setText("OPENROUTER_API_KEY")
        dialog.save_settings()
        assert cfg.openai_provider_key_env == "WORK_OPENAI_KEY"

        dialog = SettingsDialog(cfg)
        dialog.combo_llm_provider.setCurrentIndex(dialog.combo_llm_provider.findData("openai"))
        dialog.edit_api_key_env.setText("OPENAI_API_KEY")
        dialog.save_settings()
        assert cfg.openai_provider_key_env == ""
        assert cfg.openai_api_key_env == "OPENAI_API_KEY"


@gui_only
class TestMainWindowSurface:
    def test_stale_custom_entry_leaves_the_provider_list(self, tray_app):
        main = tray_app._ensure_main_window()
        main.set_llm_provider("custom")
        assert main._provider_combo.findData("custom") >= 0

        main.set_llm_provider("openrouter")

        assert main._provider_combo.findData("custom") < 0
        assert main._provider_combo.currentData() == "openrouter"
        assert [main._provider_combo.itemData(i) for i in range(main._provider_combo.count())] == [
            "openai", "openrouter"]

    def test_hide_options_popup_is_public(self, tray_app):
        main = tray_app._ensure_main_window()
        main._show_options_popup()

        main.hide_options_popup()

        assert not main._options_popup.isVisible()


@gui_only
class TestComposeRouteIsFixedAtStart:
    @pytest.fixture
    def pipeline(self, tray_app, monkeypatch, tmp_path):
        """Start a recording, then let the test change the window state before stopping."""
        from pathlib import Path
        from unittest.mock import MagicMock

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        tray_app.config._legacy_openai_api_key_value = ""
        tray_app._rebuild_llm_service()
        wav = tmp_path / "rec.wav"
        wav.write_bytes(b"RIFF")
        tray_app.audio_recorder = MagicMock()
        tray_app.audio_recorder.stop.return_value = Path(wav)
        tray_app.llm_service = MagicMock()
        tray_app.llm_service.is_available.return_value = False
        tray_app.paste_service = MagicMock()
        workers = []
        from PyQt6.QtCore import QThreadPool
        monkeypatch.setattr(QThreadPool.globalInstance(), "start", workers.append)
        monkeypatch.setattr("app.blitztext_linux.AudioRecorder.cleanup_recording", lambda p: None)
        return tray_app, workers

    def _run(self, workers):
        from unittest.mock import patch
        worker = workers[0]
        with patch("app.blitztext_linux.transcribe", return_value="hallo welt"):
            worker.run()
        return worker

    @pytest.mark.parametrize("how", ["window_closed", "routing_off"])
    def test_keyless_compose_recording_never_reaches_the_llm_after_the_window_changes(
            self, pipeline, monkeypatch, how):
        from app.workflows import WorkflowType

        app, workers = pipeline
        state = {"on": True}
        monkeypatch.setattr(app, "_compose_voice_routing_enabled", lambda: state["on"])
        app.gui_toggle_recording(WorkflowType.TEXT_IMPROVER)
        assert app.state == "RECORDING"
        state["on"] = False  # window closed / voice routing disabled mid-recording

        app.gui_toggle_recording(WorkflowType.TEXT_IMPROVER)
        worker = self._run(workers)

        app.llm_service.rewrite.assert_not_called()
        assert worker.skip_llm is True and worker.route_to_compose is False
        assert app.paste_service.method_calls, "raw text must fall back to clipboard/autopaste"
        delivered = [c.args[0] for c in app.paste_service.method_calls if c.args]
        assert delivered == ["hallo welt"]

    def test_compose_recording_with_window_still_open_is_routed_raw(self, pipeline, monkeypatch):
        from app.workflows import WorkflowType

        app, workers = pipeline
        monkeypatch.setattr(app, "_compose_voice_routing_enabled", lambda: True)
        app.gui_toggle_recording(WorkflowType.TEXT_IMPROVER)
        app.gui_toggle_recording(WorkflowType.TEXT_IMPROVER)
        worker = self._run(workers)

        app.llm_service.rewrite.assert_not_called()
        assert worker.route_to_compose is True and worker.skip_llm is True

    def test_ai_recording_without_compose_still_rewrites(self, pipeline, monkeypatch):
        from app.workflows import WorkflowType

        app, workers = pipeline
        app.llm_service.is_available.return_value = True
        app.llm_service.rewrite.return_value = "umgeschrieben"
        monkeypatch.setattr(app, "_compose_voice_routing_enabled", lambda: False)
        app.gui_toggle_recording(WorkflowType.TEXT_IMPROVER)
        app.gui_toggle_recording(WorkflowType.TEXT_IMPROVER)
        worker = self._run(workers)

        app.llm_service.rewrite.assert_called_once()
        assert worker.skip_llm is False


@gui_only
class TestSettingsDialogKeyVariables:
    def _dialog(self, cfg):
        from app.blitztext_linux import SettingsDialog
        return SettingsDialog(cfg)

    def _select(self, dialog, provider):
        dialog.combo_llm_provider.setCurrentIndex(dialog.combo_llm_provider.findData(provider))

    def test_switch_never_adopts_the_previous_providers_variable(self, tray_app):
        cfg = tray_app.config
        cfg.openai_api_key_env = "WORK_OPENAI_KEY"
        dialog = self._dialog(cfg)

        self._select(dialog, "openrouter")
        assert dialog.edit_api_key_env.text() == "OPENROUTER_API_KEY"
        self._select(dialog, "custom")
        assert dialog.edit_api_key_env.text() == ""

    def test_user_typed_names_come_back_in_both_directions(self, tray_app):
        cfg = tray_app.config
        dialog = self._dialog(cfg)
        dialog.edit_api_key_env.setText("MY_OPENAI")
        self._select(dialog, "openrouter")
        dialog.edit_api_key_env.setText("MY_ROUTER")
        self._select(dialog, "openai")
        assert dialog.edit_api_key_env.text() == "MY_OPENAI"
        self._select(dialog, "openrouter")
        assert dialog.edit_api_key_env.text() == "MY_ROUTER"

    def test_openai_to_openrouter_to_openai_through_save_and_restart(self, tray_app):
        from app.config import BlitztextConfig

        cfg = tray_app.config
        cfg.openai_api_key_env = "WORK_OPENAI_KEY"
        dialog = self._dialog(cfg)
        self._select(dialog, "openrouter")
        dialog.save_settings()
        assert (cfg.llm_provider, cfg.openai_api_key_env) == ("openrouter", "OPENROUTER_API_KEY")
        assert cfg.openai_provider_key_env == "WORK_OPENAI_KEY"

        reloaded = BlitztextConfig(config_dir=cfg.config_dir)  # restart
        dialog = self._dialog(reloaded)
        assert dialog.edit_api_key_env.text() == "OPENROUTER_API_KEY"
        self._select(dialog, "openai")
        assert dialog.edit_api_key_env.text() == "WORK_OPENAI_KEY"
        dialog.save_settings()
        assert (reloaded.llm_provider, reloaded.openai_api_key_env) == ("openai", "WORK_OPENAI_KEY")
        assert reloaded.openai_provider_key_env == ""

    def test_custom_endpoint_with_typed_variable_and_back(self, tray_app):
        from app.config import BlitztextConfig

        cfg = tray_app.config
        cfg.openai_api_key_env = "WORK_OPENAI_KEY"
        dialog = self._dialog(cfg)
        self._select(dialog, "custom")
        dialog.edit_base_url.setText("https://llm.example.org/v1")
        dialog.edit_api_key_env.setText("MY_CUSTOM_KEY")
        dialog.save_settings()
        assert (cfg.llm_provider, cfg.openai_api_key_env) == ("custom", "MY_CUSTOM_KEY")
        assert cfg.openai_provider_key_env == "WORK_OPENAI_KEY"

        dialog = self._dialog(BlitztextConfig(config_dir=cfg.config_dir))
        self._select(dialog, "openai")
        assert dialog.edit_api_key_env.text() == "WORK_OPENAI_KEY"
        self._select(dialog, "custom")
        assert dialog.edit_api_key_env.text() == "MY_CUSTOM_KEY"

    def test_custom_without_typed_variable_is_rejected_not_inherited(self, tray_app, monkeypatch):
        from unittest.mock import patch

        cfg = tray_app.config
        cfg.openai_api_key_env = "WORK_OPENAI_KEY"
        dialog = self._dialog(cfg)
        self._select(dialog, "custom")
        dialog.edit_base_url.setText("https://llm.example.org/v1")
        with patch("app.blitztext_linux.QMessageBox") as box:
            dialog.save_settings()

        box.critical.assert_called_once()
        assert (cfg.llm_provider, cfg.openai_api_key_env) == ("openai", "WORK_OPENAI_KEY")


@gui_only
class TestOpenRouterCustomKeyVariable:
    def _setup(self, tray_app, monkeypatch):
        for name in ("MY_ROUTER_KEY", "WORK_OPENAI_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.setenv(name, "dummy-not-a-real-key")
        cfg = tray_app.config
        cfg.llm_provider = "openrouter"
        cfg.llm_base_url = "https://openrouter.ai/api/v1"
        cfg.openai_api_key_env = "MY_ROUTER_KEY"
        cfg.openai_provider_key_env = "WORK_OPENAI_KEY"
        cfg.save()
        return cfg

    def test_quick_switch_round_trip_keeps_both_custom_variables(self, tray_app, monkeypatch):
        cfg = self._setup(tray_app, monkeypatch)

        tray_app.main_window_provider_changed("openai")
        assert cfg.openai_api_key_env == "WORK_OPENAI_KEY"
        assert cfg.openrouter_provider_key_env == "MY_ROUTER_KEY"

        tray_app.main_window_provider_changed("openrouter")
        assert cfg.openai_api_key_env == "MY_ROUTER_KEY"
        assert cfg.openai_provider_key_env == "WORK_OPENAI_KEY"
        assert cfg.openrouter_provider_key_env == ""

    def test_round_trip_survives_a_restart(self, tray_app, monkeypatch):
        from app.config import BlitztextConfig

        cfg = self._setup(tray_app, monkeypatch)
        tray_app.main_window_provider_changed("openai")
        tray_app.config = BlitztextConfig(config_dir=cfg.config_dir)  # restart
        tray_app.main_window_provider_changed("openrouter")

        assert tray_app.config.openai_api_key_env == "MY_ROUTER_KEY"

    def test_default_openrouter_variable_is_not_parked(self, tray_app, monkeypatch):
        cfg = self._setup(tray_app, monkeypatch)
        cfg.openai_api_key_env = "OPENROUTER_API_KEY"

        tray_app.main_window_provider_changed("openai")

        assert cfg.openrouter_provider_key_env == ""

    def test_failed_save_restores_the_parked_names(self, tray_app, monkeypatch):
        cfg = self._setup(tray_app, monkeypatch)
        monkeypatch.setattr(cfg, "save", lambda: (_ for _ in ()).throw(OSError("disk full")))

        tray_app.main_window_provider_changed("openai")

        assert (cfg.llm_provider, cfg.openai_api_key_env) == ("openrouter", "MY_ROUTER_KEY")
        assert cfg.openai_provider_key_env == "WORK_OPENAI_KEY"
        assert cfg.openrouter_provider_key_env == ""

    def test_settings_dialog_keeps_the_openrouter_variable_when_switching_to_openai(self, tray_app, monkeypatch):
        from app.blitztext_linux import SettingsDialog

        cfg = self._setup(tray_app, monkeypatch)
        dialog = SettingsDialog(cfg)
        dialog.combo_llm_provider.setCurrentIndex(dialog.combo_llm_provider.findData("openai"))
        assert dialog.edit_api_key_env.text() == "WORK_OPENAI_KEY"
        dialog.save_settings()

        assert cfg.openrouter_provider_key_env == "MY_ROUTER_KEY"
        assert cfg.openai_provider_key_env == ""
        tray_app.main_window_provider_changed("openrouter")
        assert cfg.openai_api_key_env == "MY_ROUTER_KEY"

"""Tests für das Tray-Submenu „Schreibstil-Vorlage" (Paket F).

Deckt das Zusammenspiel von Preset-Auswahl im Tray, Config-Persistenz und
LLM-Service-Neuaufbau ab:

* Auswahl im Submenu persistiert den Preset und baut den LLMService neu.
* Das Menü spiegelt jederzeit die ``config.writing_preset`` (Häkchen).
* Ein Settings-Save mit geändertem Preset gleicht das Häkchen wieder an.

GUI-gated über ``WHISPER_GUI_TESTS=1``: die echte ``BlitztextApp`` baut Tray +
QActionGroup auf und benötigt eine (Offscreen-)QApplication, analog zu
``tests/test_state_machine.py``.
"""
from __future__ import annotations

import os

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

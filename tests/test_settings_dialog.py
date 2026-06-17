"""Tests für den ``Konfigurationsdatei öffnen``-Slot des SettingsDialog.

Der Slot wird **ohne** vollständige Widget-Instanziierung getestet: Ein voller
``SettingsDialog`` unter ``QT_QPA_PLATFORM=offscreen`` bricht auf Python 3.14
beim Qt-Teardown mit SIGABRT ab (siehe ``tests/test_version.py``). Stattdessen
wird die ungebundene Methode ``SettingsDialog._open_config_file`` mit einem
leichten Stand-in für ``self`` aufgerufen.

``QDesktopServices.openUrl`` und ``QMessageBox`` werden gemockt — es startet
also **kein** echter Editor und **kein** echtes Dialogfenster. ``QUrl`` ist ein
reiner QtCore-Wertetyp und benötigt keine ``QApplication``.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.blitztext_linux import SettingsDialog
from app.config import BlitztextConfig


def _fake_self(config_dir):
    """Minimaler Stand-in für ``self``: nur das vom Slot genutzte ``config``."""
    return SimpleNamespace(config=BlitztextConfig(config_dir=config_dir))


def test_open_config_creates_missing_file(tmp_path):
    fake = _fake_self(tmp_path / ".config" / "blitztext-linux")
    assert not fake.config.config_file.is_file()

    with patch("app.blitztext_linux.QDesktopServices.openUrl", return_value=True) as m_open, \
            patch("app.blitztext_linux.QMessageBox") as m_box:
        SettingsDialog._open_config_file(fake)

    # Fehlende config.json wird über config.save() angelegt.
    assert fake.config.config_file.is_file()
    m_open.assert_called_once()
    m_box.warning.assert_not_called()
    m_box.critical.assert_not_called()


def test_open_config_passes_correct_local_path(tmp_path):
    fake = _fake_self(tmp_path / ".config" / "blitztext-linux")

    with patch("app.blitztext_linux.QDesktopServices.openUrl", return_value=True) as m_open, \
            patch("app.blitztext_linux.QMessageBox"):
        SettingsDialog._open_config_file(fake)

    # openUrl wird mit dem korrekten lokalen config.json-Pfad aufgerufen.
    (url_arg,) = m_open.call_args.args
    assert url_arg.toLocalFile() == str(fake.config.config_file)


def test_open_config_does_not_resave_existing_file(tmp_path):
    fake = _fake_self(tmp_path / ".config" / "blitztext-linux")
    fake.config.save()  # Datei existiert bereits.

    with patch.object(type(fake.config), "save") as m_save, \
            patch("app.blitztext_linux.QDesktopServices.openUrl", return_value=True), \
            patch("app.blitztext_linux.QMessageBox"):
        SettingsDialog._open_config_file(fake)

    m_save.assert_not_called()


def test_open_config_handles_save_error_before_open(tmp_path):
    fake = _fake_self(tmp_path / ".config" / "blitztext-linux")  # Datei fehlt -> save() wird versucht.

    with patch.object(type(fake.config), "save", side_effect=OSError("disk full")), \
            patch("app.blitztext_linux.QDesktopServices.openUrl") as m_open, \
            patch("app.blitztext_linux.QMessageBox") as m_box:
        SettingsDialog._open_config_file(fake)  # darf nicht werfen

    # save() schlägt fehl -> critical-Dialog, openUrl wird gar nicht erreicht.
    m_open.assert_not_called()
    m_box.critical.assert_called_once()
    m_box.warning.assert_not_called()


def test_open_config_handles_open_failure(tmp_path):
    fake = _fake_self(tmp_path / ".config" / "blitztext-linux")

    with patch("app.blitztext_linux.QDesktopServices.openUrl", return_value=False) as m_open, \
            patch("app.blitztext_linux.QMessageBox") as m_box:
        SettingsDialog._open_config_file(fake)  # darf nicht werfen

    # Rückgabe False -> saubere Warnung statt Exception.
    m_open.assert_called_once()
    m_box.warning.assert_called_once()
    m_box.critical.assert_not_called()

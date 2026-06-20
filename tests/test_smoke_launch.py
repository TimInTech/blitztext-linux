"""Launch-Smoke-Test: bootet die App offscreen noch und beendet sauber?

Zweck: bei jedem Push automatisch beantworten, ob sich die echte App noch
hochfahren laesst. Der Test konstruiert dieselbe ``BlitztextApp`` wie der
Produktiv-Einstiegspunkt ``main()`` (QApplication + Tray + Hauptfenster),
laesst einen echten Qt-Event-Loop kurz idlen und prueft, dass er sauber mit
Exit 0 zurueckkehrt.

Bewusst NICHT ueber ``main()``: ``main()`` ruft ``QApplication(sys.argv)`` neu
auf und wuerde im selben Prozess mit dem von der GUI-Suite wiederverwendeten
QApplication-Singleton kollidieren; ausserdem bricht ``_require_display_environment``
unter Offscreen (kein DISPLAY) ab. Wir spiegeln daher den Boot-Pfad in-process,
analog zu ``tests/test_state_machine.py`` (Fixture ``gui_app``).

Kein echter Hotkey/evdev-Thread (``stop_hotkey_worker`` vor dem Idle), kein
echtes Audio, keine echte Whisper/Piper-Nutzung. GUI-gated ueber
``WHISPER_GUI_TESTS=1`` (Display/Offscreen noetig).
"""
import os
from unittest.mock import patch

import pytest

from app.i18n import DEFAULT_LANGUAGE, get_language, set_language, t

_GUI = os.environ.get("WHISPER_GUI_TESTS") == "1"
gui_only = pytest.mark.skipif(not _GUI, reason="benötigt WHISPER_GUI_TESTS=1 (Display)")


@gui_only
@pytest.mark.parametrize("ui_language", ["de", "en"])
def test_app_boots_idles_and_exits_clean(ui_language, tmp_path):
    """Echte App bootet offscreen, idlet kurz und beendet mit Exit 0."""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    from app.blitztext_linux import BlitztextApp
    from app.config import Config

    config = Config.load(tmp_path / "config.json")
    config.ui_language = ui_language

    qapp = QApplication.instance() or QApplication([])
    app = None
    try:
        with patch("app.blitztext_linux.Config.load", return_value=config):
            app = BlitztextApp(qapp)
        # Kein echter evdev-Thread waehrend des Idle-Loops (Pattern aus gui_app).
        app.stop_hotkey_worker()
        # Hauptfenster offscreen hochfahren -- exakt wie main().
        app.show_main_window()

        # Kurz idlen, dann deterministisch sauber beenden.
        QTimer.singleShot(50, qapp.quit)
        exit_code = qapp.exec()

        assert exit_code == 0
        assert get_language() == ui_language

        # Regressionsschutz: Hauptfenster- und Tray-Texte laufen über t() und
        # spiegeln die aktive Sprache. Fängt vergessene Call-Sites ab, die der
        # reine Key-Vollständigkeitstest (test_i18n) nicht erkennt. Bewusst im
        # selben Boot wie der Smoke-Test (kein zweiter BlitztextApp im Prozess,
        # um QObject-Leaks in Folgetests zu vermeiden).
        win = app._main_window
        assert win._btn_discard.text() == t("mainwindow.button.discard")
        assert win._btn_dictation.text() == t("mainwindow.button.dictation")
        assert win._btn_history.text() == t("mainwindow.button.history").format(count=0)
        assert win._btn_tts.toolTip() == t("mainwindow.tooltip.tts")
        assert win._btn_settings.toolTip() == t("mainwindow.tooltip.settings")
        assert win._status_label.text() == t("mainwindow.status.ready")
        assert app.action_dictation.text() == t("tray.dictation_mode")
        assert app.action_history.text() == t("tray.history")
        assert app.action_tts.text() == t("tray.tts")

        # Sprachabhängigkeit echt verankern (nicht nur Tautologie über t()).
        if ui_language == "en":
            assert "Discard" in win._btn_discard.text()
            assert "History" in app.action_history.text()
        else:
            assert "Verwerfen" in win._btn_discard.text()
            assert "Verlauf" in app.action_history.text()
    finally:
        # Idempotentes Cleanup, damit kein Thread in Folgetests nachhaengt.
        if app is not None:
            app.stop_hotkey_worker()
        set_language(DEFAULT_LANGUAGE)

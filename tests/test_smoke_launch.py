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

import pytest

_GUI = os.environ.get("WHISPER_GUI_TESTS") == "1"
gui_only = pytest.mark.skipif(not _GUI, reason="benötigt WHISPER_GUI_TESTS=1 (Display)")


@gui_only
def test_app_boots_idles_and_exits_clean():
    """Echte App bootet offscreen, idlet kurz und beendet mit Exit 0."""
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    from app.blitztext_linux import BlitztextApp

    qapp = QApplication.instance() or QApplication([])
    app = BlitztextApp(qapp)
    # Kein echter evdev-Thread waehrend des Idle-Loops (Pattern aus gui_app).
    app.stop_hotkey_worker()
    # Hauptfenster offscreen hochfahren -- exakt wie main().
    app.show_main_window()

    # Kurz idlen, dann deterministisch sauber beenden.
    QTimer.singleShot(50, qapp.quit)
    exit_code = qapp.exec()

    assert exit_code == 0

    # Idempotentes Cleanup, damit kein Thread in Folgetests nachhaengt.
    app.stop_hotkey_worker()

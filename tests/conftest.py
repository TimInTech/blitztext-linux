"""Globale Test-Fixtures fuer die BlitztextLinux-Suite.

Wichtigster Zweck: verhindern, dass Tests echte Desktop-Benachrichtigungen
ausloesen. ``app.notify.notify`` startet ``notify-send`` als externen Prozess --
das ist unabhaengig von ``QT_QPA_PLATFORM=offscreen`` und wuerde bei jedem
Testlauf auf einem Desktop mit ``notify-send`` ein sichtbares Popup erzeugen
(z. B. "Blitztext Fehler: boom" aus den Worker-Error-Tests). Die autouse-Fixture
ersetzt deshalb ``subprocess.run`` im notify-Modul durch einen Mock.

Tests, die das notify-Verhalten gezielt pruefen (``tests/test_features.py``),
legen innerhalb ihres ``with patch(...)``-Blocks einen eigenen, verschachtelten
Patch an und bleiben dadurch unveraendert gueltig.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _block_real_notifications():
    """Unterbindet echte ``notify-send``-Aufrufe in der gesamten Testsuite."""
    with patch("app.notify.subprocess.run", MagicMock()):
        yield

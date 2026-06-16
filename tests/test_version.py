"""Tests für die zentrale App-Versionsquelle.

Prüft, dass ``app.__version__`` definiert und semver-förmig ist.

Die optische Versionszeile im „Allgemein"-Tab des Einstellungen-Dialogs wird
nicht automatisiert getestet: ein voller ``SettingsDialog`` unter
``QT_QPA_PLATFORM=offscreen`` bricht beim Qt-Teardown (Python 3.14) mit SIGABRT
ab. Die Anzeige wird daher manuell/visuell verifiziert (siehe Handover).
"""
from __future__ import annotations

import re

from app import __version__

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def test_version_is_defined_and_semver() -> None:
    assert isinstance(__version__, str)
    assert SEMVER.match(__version__), f"unerwartetes Versionsformat: {__version__!r}"

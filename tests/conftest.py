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

Zweiter Zweck: deterministischer Abbau geleakter Qt-Objekte zwischen Tests
(siehe ``_collect_leaked_qobjects``).
"""
from __future__ import annotations

import gc
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _block_real_notifications():
    """Unterbindet echte ``notify-send``-Aufrufe in der gesamten Testsuite."""
    with patch("app.notify.subprocess.run", MagicMock()):
        yield


@pytest.fixture(autouse=True)
def _collect_leaked_qobjects():
    """Sammelt nach JEDEM Test geleakte, parentlose QObjects deterministisch ein.

    Root Cause der Python-3.12-Testisolation (``RuntimeError: wrapped C/C++
    object of type HotkeyWorker has been deleted``): Mehrere GUI-Tests erzeugen
    ``BlitztextApp`` (selbst ein ``QObject``) samt ``HotkeyWorker``, ``QThread``
    und Fenstern ohne Qt-Parent und lassen die Python-Referenz am Testende
    einfach fallen. Weil diese Objekte in Referenzzyklen haengen (Signal-/Slot-
    Verbindungen zeigen auf ``self``), raeumt der Refcount sie nicht ab -- erst
    Pythons zyklischer Garbage Collector loescht die zugehoerigen C++-Objekte,
    und zwar zu einem nichtdeterministischen Zeitpunkt. Auf CPython 3.12 faellt
    dieser GC-Lauf reproduzierbar mitten in ein ``HotkeyWorker.run()`` eines
    Folgetests (``tests/test_state_machine.py::TestLeftAltEvents``); sip meldet
    dann den gerade laufenden Worker als geloescht, sobald ``run()`` das naechste
    Mal auf ``self`` (z. B. ``self.workflow_triggered``) zugreift.

    Ein explizites ``gc.collect()`` an der Testgrenze macht diesen Abbau
    deterministisch: die geleakten Zyklen werden eingesammelt, WAEHREND kein
    Worker laeuft. Im Folgetest bleibt fuer den GC nichts mehr einzusammeln, das
    mit einem laufenden ``run()`` kollidieren koennte.

    Bewusst NUR ``gc.collect()``: kein ``processEvents``/``DeferredDelete``-Pump,
    da dieser noch von Tests referenzierte Widgets vorzeitig loeschen und
    C++-seitige Doppel-Frees ausloesen kann. ``gc.collect()`` bricht nur echte,
    unerreichbare Zyklen auf und ist damit nebenwirkungsfrei.
    """
    yield
    gc.collect()

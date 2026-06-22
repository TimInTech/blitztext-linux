"""Unit-Tests für die reinen Hilfsfunktionen aus ``scripts/_make_screenshots.py``.

Das Skript ist ein manuell ausgeführter Asset-Generator (Banner + Screenshots)
und kein Teil der ausgelieferten App. Getestet werden daher gezielt die reinen,
deterministischen Funktionen, die ohne ``QApplication`` auskommen:

* ``_resize_card`` – Bild laden, einpassen, zentrieren (inkl. Fehlerpfade)
* ``_draw_multiline`` – Wortumbruch-Logik
* ``_font`` – Font-Fallback liefert immer eine nutzbare Schrift
* ``_tab_index`` – sprach- und reihenfolgenstabiler Settings-Tab-Lookup

``scripts/`` ist kein Package; das Modul wird daher per ``importlib`` über den
Dateipfad geladen. Ein reiner Import erzeugt keine ``QApplication`` (verifiziert),
sodass die Tests ungated laufen können.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# Pillow ist eine reine Dev-/Tooling-Abhängigkeit (siehe requirements-dev.txt).
# Fehlt sie in einer Teilumgebung, werden diese Tests sauber übersprungen statt
# die Collection der gesamten Suite abzubrechen.
pytest.importorskip("PIL")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.i18n import set_language, t  # noqa: E402

_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "_make_screenshots.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_make_screenshots_under_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


screenshots = _load_module()


# --------------------------------------------------------------------------- #
# _resize_card
# --------------------------------------------------------------------------- #
def test_resize_card_centers_image_on_transparent_canvas(tmp_path):
    # Arrange: ein 50x50-Bild, eingepasst in eine 100x100-Karte
    source = tmp_path / "src.png"
    Image.new("RGBA", (50, 50), (255, 0, 0, 255)).save(source)

    # Act
    card = screenshots._resize_card(source, (100, 100))

    # Assert: Kartengröße exakt, Inhalt zentriert (25px Rand), Ecken transparent
    assert card.size == (100, 100)
    assert card.getpixel((50, 50))[3] == 255  # Mitte deckend
    assert card.getpixel((0, 0))[3] == 0       # Ecke transparent


def test_resize_card_preserves_aspect_ratio(tmp_path):
    # Arrange: 200x100 (2:1) in eine 50x50-Karte
    source = tmp_path / "wide.png"
    Image.new("RGBA", (200, 100), (0, 128, 255, 255)).save(source)

    # Act
    card = screenshots._resize_card(source, (50, 50))

    # Assert: thumbnail vergrößert nie und hält das Seitenverhältnis (≤ Zielgröße)
    assert card.size == (50, 50)


def test_resize_card_raises_filenotfound_for_missing_screenshot(tmp_path):
    # Arrange / Act / Assert
    missing = tmp_path / "does-not-exist.png"
    with pytest.raises(FileNotFoundError):
        screenshots._resize_card(missing, (100, 100))


def test_resize_card_raises_oserror_for_corrupt_image(tmp_path):
    # Arrange: vorhandene, aber kaputte PNG-Datei
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not a real png")

    # Act / Assert
    with pytest.raises(OSError):
        screenshots._resize_card(corrupt, (100, 100))


# --------------------------------------------------------------------------- #
# _draw_multiline
# --------------------------------------------------------------------------- #
def test_draw_multiline_empty_string_returns_start_y():
    # Arrange
    image = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = screenshots._font(15)

    # Act
    end_y = screenshots._draw_multiline(draw, "", (10, 30), width=180, font=font, fill="#ffffff")

    # Assert: keine Zeile gezeichnet -> y unverändert
    assert end_y == 30


def test_draw_multiline_wraps_long_text_to_multiple_lines():
    # Arrange: Text, der bei schmaler Breite mehrere Zeilen erzwingt
    image = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = screenshots._font(15)
    text = "the quick brown fox jumps over the lazy dog repeatedly today"

    # Act
    end_y = screenshots._draw_multiline(draw, text, (0, 0), width=80, font=font, fill="#ffffff")

    # Assert: mehrzeilig -> Endposition liegt mindestens zwei Zeilenhöhen tiefer
    assert end_y > (font.size + 6) * 2


# --------------------------------------------------------------------------- #
# _font
# --------------------------------------------------------------------------- #
def test_font_returns_usable_font_object():
    # Act
    font = screenshots._font(24, bold=True)

    # Assert
    assert font is not None
    assert isinstance(font, (ImageFont.FreeTypeFont, ImageFont.ImageFont))


def test_font_falls_back_to_default_when_no_files_present(monkeypatch):
    # Arrange: keine Font-Datei wird gefunden -> Fallback auf load_default
    monkeypatch.setattr(screenshots.Path, "is_file", lambda self: False)

    # Act
    font = screenshots._font(24)

    # Assert: kein Crash, weiterhin eine nutzbare Schrift
    assert isinstance(font, (ImageFont.FreeTypeFont, ImageFont.ImageFont))


# --------------------------------------------------------------------------- #
# _tab_index  (Regressionsschutz: vormals zeigte "ai-workflows" auf den
#              falschen Index 2 = General statt 1 = Workflows)
# --------------------------------------------------------------------------- #
class _FakeTabs:
    """Minimaler QTabWidget-Stub: bildet nur count() und tabText() ab."""

    def __init__(self, titles: list[str]) -> None:
        self._titles = titles

    def count(self) -> int:
        return len(self._titles)

    def tabText(self, index: int) -> str:
        return self._titles[index]


@pytest.mark.parametrize("lang", ["en", "de"])
def test_tab_index_resolves_keys_independent_of_language(lang):
    # Arrange: reale Tab-Reihenfolge speech, workflows, general in aktueller Sprache
    set_language(lang)
    tabs = _FakeTabs([
        t("settings.tab.speech"),
        t("settings.tab.workflows"),
        t("settings.tab.general"),
    ])

    # Act / Assert: Lookup trifft die korrekten Indizes (Workflows == 1, nicht 2)
    assert screenshots._tab_index(tabs, "settings.tab.speech") == 0
    assert screenshots._tab_index(tabs, "settings.tab.workflows") == 1
    assert screenshots._tab_index(tabs, "settings.tab.general") == 2


def test_tab_index_raises_for_unknown_tab():
    # Arrange
    set_language("en")
    tabs = _FakeTabs([t("settings.tab.general")])

    # Act / Assert
    with pytest.raises(ValueError):
        screenshots._tab_index(tabs, "settings.tab.workflows")

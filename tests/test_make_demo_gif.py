"""Unit-Tests für die reinen Hilfsfunktionen aus ``scripts/_make_demo_gif.py``.

Das Skript ist ein manuell ausgeführter Asset-Generator (README-Demo-GIF)
und kein Teil der ausgelieferten App. Getestet werden die reinen,
deterministischen Funktionen (kein Qt, nur Pillow):

* ``_typewriter_chunks`` – progressive Präfixe für die Tipp-Animation
* ``_wrap_lines`` – Wortumbruch-Logik
* ``_load_tray_icon`` – Laden + Einpassen der Tray-Icons (inkl. Fehlerpfad)
* ``_scale_app_window`` – Skalierung der echten Fenster-Grabs
* ``_build_frames`` / ``_save_gif`` – Frame-Aufbau und GIF-Ausgabe

Die echten Fenster-Zustände (``_grab_app_states``) benötigen eine
``QApplication`` und werden hier durch einfache Platzhalter-Bilder ersetzt.

``scripts/`` ist kein Package; das Modul wird daher per ``importlib`` über den
Dateipfad geladen. Ein reiner Import erzeugt keine ``QApplication``, sodass die
Tests ungated laufen können.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# Pillow ist eine reine Dev-/Tooling-Abhängigkeit (siehe requirements-dev.txt).
pytest.importorskip("PIL")

from PIL import Image, ImageDraw  # noqa: E402

_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "_make_demo_gif.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_make_demo_gif_under_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


demo = _load_module()


# --------------------------------------------------------------------------- #
# _typewriter_chunks
# --------------------------------------------------------------------------- #
def test_typewriter_chunks_are_progressive_and_end_with_full_text():
    # Arrange
    text = "Hallo Anna, bis gleich."

    # Act
    chunks = demo._typewriter_chunks(text, chunk=3)

    # Assert: jeder Frame verlängert den vorherigen, letzter Frame = Volltext
    assert chunks[-1] == text
    for earlier, later in zip(chunks, chunks[1:], strict=False):
        assert later.startswith(earlier)
        assert len(later) > len(earlier)


def test_typewriter_chunks_empty_text_yields_no_frames():
    # Act / Assert
    assert demo._typewriter_chunks("") == []


def test_typewriter_chunks_short_text_yields_single_full_frame():
    # Arrange: Text kürzer als die Chunk-Größe
    chunks = demo._typewriter_chunks("Hi", chunk=10)

    # Assert
    assert chunks == ["Hi"]


def test_typewriter_chunks_rejects_invalid_chunk_size():
    # Act / Assert
    with pytest.raises(ValueError):
        demo._typewriter_chunks("Hallo", chunk=0)


# --------------------------------------------------------------------------- #
# _wrap_lines
# --------------------------------------------------------------------------- #
def test_wrap_lines_wraps_long_text_and_preserves_all_words():
    # Arrange
    image = Image.new("RGBA", (200, 200))
    draw = ImageDraw.Draw(image)
    font = demo._font(15)
    text = "the quick brown fox jumps over the lazy dog repeatedly today"

    # Act
    lines = demo._wrap_lines(draw, text, font, width=80)

    # Assert: mehrzeilig, kein Wortverlust
    assert len(lines) >= 2
    assert " ".join(lines) == text


def test_wrap_lines_empty_text_returns_no_lines():
    # Arrange
    image = Image.new("RGBA", (100, 100))
    draw = ImageDraw.Draw(image)

    # Act / Assert
    assert demo._wrap_lines(draw, "", demo._font(15), width=80) == []


# --------------------------------------------------------------------------- #
# _load_tray_icon
# --------------------------------------------------------------------------- #
def test_load_tray_icon_fits_icon_into_requested_size():
    # Act: echtes Repo-Asset (128x128) auf 30px einpassen
    icon = demo._load_tray_icon("tray-idle.png", size=30)

    # Assert
    assert max(icon.size) <= 30
    assert icon.mode == "RGBA"


def test_load_tray_icon_raises_filenotfound_for_missing_asset():
    # Act / Assert
    with pytest.raises(FileNotFoundError):
        demo._load_tray_icon("does-not-exist.png")


# --------------------------------------------------------------------------- #
# _scale_app_window
# --------------------------------------------------------------------------- #
def test_scale_app_window_scales_by_configured_factor():
    # Arrange: 100x80 wächst mit Faktor 1.5 auf 150x120
    source = Image.new("RGBA", (100, 80), (10, 20, 30, 255))

    # Act
    scaled = demo._scale_app_window(source, scale=1.5)

    # Assert
    assert scaled.size == (150, 120)


# --------------------------------------------------------------------------- #
# _build_frames / _save_gif
# --------------------------------------------------------------------------- #
def _demo_icons() -> dict:
    icon = Image.new("RGBA", (30, 30), (0, 255, 0, 255))
    return {"idle": icon, "recording": icon, "processing": icon}


def _demo_app_states() -> dict:
    """Platzhalter für die echten MainWindow-Grabs (Qt-frei)."""
    window = Image.new("RGBA", (384, 389), (40, 44, 48, 255))
    return {
        "idle": window,
        "recording-1": window,
        "recording-2": window,
        "recording-3": window,
        "transcribing": window,
    }


@pytest.mark.parametrize("lang", ["en", "de"])
def test_build_frames_produces_uniform_frames_with_positive_durations(lang):
    # Act
    frames = demo._build_frames(lang, _demo_icons(), _demo_app_states())

    # Assert: genug Frames für alle Szenen, einheitliche Größe, gültige Dauern
    assert len(frames) > 20
    for image, duration in frames:
        assert image.size == demo.CANVAS_SIZE
        assert duration > 0


def test_save_gif_writes_animated_gif(tmp_path):
    # Arrange: zwei minimale Frames
    frames = [
        (Image.new("RGBA", (40, 40), (255, 0, 0, 255)), 100),
        (Image.new("RGBA", (40, 40), (0, 0, 255, 255)), 100),
    ]
    out = tmp_path / "demo.gif"

    # Act
    demo._save_gif(frames, out)

    # Assert: animiertes GIF mit beiden Frames
    with Image.open(out) as gif:
        assert gif.format == "GIF"
        assert gif.n_frames == 2


def test_save_gif_rejects_empty_frame_list(tmp_path):
    # Act / Assert
    with pytest.raises(ValueError):
        demo._save_gif([], tmp_path / "empty.gif")

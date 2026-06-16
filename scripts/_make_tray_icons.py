"""Rendert die Tray-Icon-Zustaende von BlitztextLinux als PNG.

Erzeugt einzelne Icons je Status sowie ein beschriftetes Uebersichtsbild fuer
die README. Die Zeichnung spiegelt 1:1 `BlitztextApp._create_microphone_icon`.

Aufruf:  PYTHONPATH=. .venv/bin/python scripts/_make_tray_icons.py <out_dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication

# Status → (Farbe, Label) — exakt wie in blitztext_linux.py
STATES = [
    ("idle", "#2e7d32", "Bereit"),
    ("recording", "#c62828", "Aufnahme"),
    ("processing", "#ef6c00", "Verarbeitung"),
    ("error", "#757575", "Fehler"),
]

SCALE = 2  # 64 → 128 px fuer schaerfere Darstellung


def _draw_mic(painter: QPainter, color: QColor) -> None:
    """Identische Mikrofon-Geometrie wie im Tray (Basis 64x64)."""
    painter.setPen(QPen(color, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(QBrush(color))
    painter.drawRoundedRect(23, 8, 18, 29, 9, 9)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(15, 23, 34, 25, 200 * 16, 140 * 16)
    painter.drawLine(32, 46, 32, 55)
    painter.drawLine(24, 55, 40, 55)


def _single(color: QColor) -> QPixmap:
    size = 64 * SCALE
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(SCALE, SCALE)
    _draw_mic(p, color)
    p.end()
    return pm


def main() -> int:
    out_dir = Path(sys.argv[1]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)  # noqa: F841 — QPixmap braucht QApplication

    # Einzel-Icons
    for key, hexcol, _label in STATES:
        _single(QColor(hexcol)).save(str(out_dir / f"tray-{key}.png"))
        print(f"  ✓ tray-{key}.png")

    # Uebersichtsbild: 4 Kacheln nebeneinander, Icon + Label
    tile_w, tile_h, icon = 150, 170, 96
    pad = 18
    total_w = pad + len(STATES) * (tile_w + pad)
    total_h = tile_h + 2 * pad
    canvas = QPixmap(total_w, total_h)
    canvas.fill(QColor("#fafafa"))
    cp = QPainter(canvas)
    cp.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont()
    font.setPointSize(12)
    font.setBold(True)
    cp.setFont(font)

    for i, (key, hexcol, label) in enumerate(STATES):
        x = pad + i * (tile_w + pad)
        # Kachel
        cp.setPen(QPen(QColor("#e0e0e0"), 1))
        cp.setBrush(QBrush(QColor("#ffffff")))
        cp.drawRoundedRect(QRectF(x, pad, tile_w, tile_h), 12, 12)
        # Icon zentriert
        ic = _single(QColor(hexcol)).scaled(
            icon, icon, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        cp.drawPixmap(int(x + (tile_w - icon) / 2), pad + 18, ic)
        # Label zentriert ueber volle Kachelbreite (Icon-Farbe zeigt den Status)
        label_y = pad + 18 + icon + 12
        cp.setPen(QPen(QColor("#222222")))
        cp.drawText(
            QRectF(x, label_y, tile_w, 24),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            label,
        )
    cp.end()
    canvas.save(str(out_dir / "tray-states.png"))
    print("  ✓ tray-states.png")
    print("Fertig.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

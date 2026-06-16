"""Design-System fuer BlitztextLinux (Breeze-Dark / Glass-Idiom).

Uebersetzt das exportierte Blitztext Design System (Tokens, Glass-UI-Kit) in
PyQt6: ein globales QSS-Stylesheet plus das Marken-App-Icon (Mikrofon + Blitz).

Farb- und Radius-Werte stammen 1:1 aus `tokens/colors.css` und
`tokens/spacing.css` des Design-Systems:
  - Breeze-Dark-Flaechen (#1b1e20 / #2a2e32 / #31363b / #41464c)
  - Brand-Amber  --blitz-500 #e0a90f / --blitz-300 #f2cd4f
  - Breeze-Blau  #3daee9 (OS-Akzent, Fokus)
  - Status: idle #2e7d32, recording #c62828, processing #ef6c00, error #757575
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap

# --- Token-Konstanten (aus dem Design-System) -----------------------------
BLITZ_500 = "#e0a90f"
BLITZ_400 = "#ecbb2a"
BLITZ_300 = "#f2cd4f"

BREEZE_VIEW = "#1b1e20"
BREEZE_WINDOW = "#2a2e32"
BREEZE_BUTTON = "#31363b"
BREEZE_BUTTON_HOV = "#3b4045"
BREEZE_LINE = "#41464c"
BREEZE_BLUE = "#3daee9"

APP_TEXT = "#f4f6f8"
APP_TEXT_DIM = "#9ba2ab"
APP_TEXT_FAINT = "#6e757e"

# Feine Hairline-Borders statt voller Linienfarbe (dezenter Glass-Look)
HAIRLINE = "rgba(255, 255, 255, 0.08)"
HAIRLINE_STRONG = "rgba(255, 255, 255, 0.16)"

STATE_IDLE = "#2e7d32"
STATE_RECORDING = "#c62828"
STATE_PROCESSING = "#ef6c00"
STATE_ERROR = "#757575"

ASSETS_DIR = Path(__file__).resolve().parent / "assets"


# --- Globales QSS-Stylesheet ----------------------------------------------
# Modernes Breeze-Dark mit weichen Rundungen, dezenten Hairlines und einem
# Breeze-Blau-Fokusring. Bewusst zurueckhaltend, damit es im KDE-Tray sauber
# wirkt und Dialoge (Einstellungen, Verlauf) konsistent aussehen.
APP_QSS = f"""
* {{
    color: {APP_TEXT};
    font-size: 12px;
}}

QWidget {{
    background-color: {BREEZE_WINDOW};
}}

QLabel {{
    background: transparent;
}}

/* Standard-Buttons: kompakt, Hairline-Border, klare Zustaende */
QPushButton {{
    background-color: {BREEZE_BUTTON};
    border: 1px solid {HAIRLINE};
    border-radius: 8px;
    padding: 3px 8px;
    color: {APP_TEXT};
}}
QPushButton:hover {{
    background-color: {BREEZE_BUTTON_HOV};
    border-color: {HAIRLINE_STRONG};
}}
QPushButton:pressed {{
    background-color: #272b2f;
    border-color: {HAIRLINE};
}}
QPushButton:focus {{
    border-color: rgba(61, 174, 233, 0.65);
    outline: none;
}}
QPushButton:disabled {{
    color: {APP_TEXT_FAINT};
    background-color: #2d3135;
    border-color: rgba(255, 255, 255, 0.04);
}}
QPushButton:checked {{
    background-color: rgba(224, 169, 15, 0.14);
    border-color: rgba(224, 169, 15, 0.40);
    color: {BLITZ_300};
}}

/* Eingaben & Auswahl */
QComboBox, QLineEdit, QSpinBox, QPlainTextEdit, QTextEdit {{
    background-color: {BREEZE_VIEW};
    border: 1px solid {HAIRLINE};
    border-radius: 8px;
    padding: 4px 8px;
    selection-background-color: {BREEZE_BLUE};
}}
QComboBox:hover, QLineEdit:hover {{
    border-color: {HAIRLINE_STRONG};
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: rgba(61, 174, 233, 0.55);
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox::down-arrow {{
    image: url({(ASSETS_DIR / "chevron-down.svg").as_posix()});
    width: 12px;
    height: 12px;
}}
QComboBox QAbstractItemView {{
    background-color: {BREEZE_VIEW};
    border: 1px solid {HAIRLINE_STRONG};
    border-radius: 8px;
    selection-background-color: {BREEZE_BLUE};
    outline: none;
}}

/* Tabs (Einstellungen) */
QTabWidget::pane {{
    border: 1px solid {HAIRLINE};
    border-radius: 10px;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {APP_TEXT_DIM};
    padding: 6px 12px;
    border: none;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    color: {APP_TEXT};
    border-bottom: 2px solid {BLITZ_500};
}}
QTabBar::tab:hover:!selected {{
    color: {APP_TEXT};
}}

QCheckBox {{
    background: transparent;
    spacing: 8px;
}}

QToolTip {{
    background-color: {BREEZE_VIEW};
    color: {APP_TEXT};
    border: 1px solid {HAIRLINE_STRONG};
    padding: 3px 6px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #4b515a;
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


def apply_theme(app) -> None:
    """Wendet das Blitztext-Glass-Theme global auf die QApplication an."""
    app.setStyleSheet(APP_QSS)


def create_app_icon() -> QIcon:
    """Marken-App-Icon: Mikrofon (hell) + Blitz (amber) auf dunklem Grund.

    Bevorzugt das gelieferte SVG aus dem Design-System; faellt auf eine
    programmatische Variante zurueck, falls der SVG-Loader fehlt.
    """
    svg_path = ASSETS_DIR / "logo-mark-dark.svg"
    if svg_path.exists():
        icon = QIcon(str(svg_path))
        if not icon.isNull() and icon.availableSizes():
            return icon
    return _painted_app_icon()


def _painted_app_icon() -> QIcon:
    """Fallback-Icon im Code gezeichnet (Mikrofon + Blitz, Breeze-Dark)."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # dunkler abgerundeter Hintergrund
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(BREEZE_WINDOW)))
    painter.drawRoundedRect(4, 4, 56, 56, 14, 14)

    # Mikrofon (hell)
    mic = QColor("#fcfcfc")
    painter.setPen(QPen(mic, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(QBrush(mic))
    painter.drawRoundedRect(23, 14, 14, 22, 7, 7)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(17, 28, 30, 22, 200 * 16, 140 * 16)
    painter.drawLine(32, 47, 32, 54)
    painter.drawLine(25, 54, 39, 54)

    # Blitz (amber)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(BLITZ_500)))
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QPolygonF
    bolt = QPolygonF([
        QPointF(34, 13), QPointF(26, 25), QPointF(31, 25),
        QPointF(28, 34), QPointF(38, 22), QPointF(33, 22),
    ])
    painter.drawPolygon(bolt)
    painter.end()
    return QIcon(pixmap)

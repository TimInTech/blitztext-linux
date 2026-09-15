"""Central dark-neumorphic design system for the native Blitztext UI."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)

# --- Token-Konstanten (aus dem Design-System) -----------------------------
BLITZ_500 = "#d6b260"
BLITZ_400 = "#e6c878"
BLITZ_300 = "#f4dda0"

APP_BACKGROUND = "#151719"
APP_WINDOW = "#1b1d20"
APP_SURFACE = "#24272b"
APP_SURFACE_RAISED = "#2c3035"
APP_SURFACE_HOVER = "#353a40"
APP_SURFACE_SUNK = "#17191c"
APP_SURFACE_DISABLED = "#202327"
APP_LINE = "#3b4047"
APP_LINE_SOFT = "rgba(255, 255, 255, 0.07)"
APP_LINE_STRONG = "rgba(255, 255, 255, 0.14)"

# Compatibility aliases used by older widgets while they share the new world.
BREEZE_VIEW = APP_SURFACE_SUNK
BREEZE_WINDOW = APP_WINDOW
BREEZE_BUTTON = APP_SURFACE_RAISED
BREEZE_BUTTON_HOV = APP_SURFACE_HOVER
BREEZE_LINE = APP_LINE
BREEZE_BLUE = BLITZ_500

APP_TEXT = "#f2f1ed"
APP_TEXT_DIM = "#bab8b1"
APP_TEXT_FAINT = "#8e8d88"

HAIRLINE = APP_LINE_SOFT
HAIRLINE_STRONG = APP_LINE_STRONG

STATE_IDLE = "#86c99a"
STATE_RECORDING = BLITZ_400
STATE_PROCESSING = BLITZ_300
STATE_ERROR = "#e88787"
STATE_WARNING = "#e7bd70"

# Record button: round microphone plus room for the recording waves beside it.
RECORD_BUTTON_WIDTH = 160
RECORD_BUTTON_HEIGHT = 98
TOOL_BUTTON_SIZE = 32
TOOL_ICON_SIZE = 18
WINDOW_BUTTON_SIZE = 22

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

# Official Blitztext mark (identical to blitztextweb/brand/logo-mark-dark.svg).
BRAND_MARK_SVG = ASSETS_DIR / "logo-mark-dark.svg"
_BRAND_BOLT_FILL = "#e0a90f"
# Same geometry as the asset; only used if the asset cannot be read.
_BRAND_CAPSULE_FALLBACK = (16.0, 6.0, 16.0, 26.0)
_BRAND_BOLT_FALLBACK = "M26 11l-6 9h4l-2 7 6-9.5h-4z"


APP_QSS = f"""
* {{
    color: {APP_TEXT};
    font-size: 12px;
    selection-background-color: {BLITZ_500};
    selection-color: #19150d;
}}

QWidget, QDialog {{
    background-color: {APP_WINDOW};
}}

QLabel {{
    background: transparent;
}}
QLabel[role="secondary"] {{ color: {APP_TEXT_DIM}; }}
QLabel[role="muted"] {{ color: {APP_TEXT_FAINT}; }}
QLabel[role="title"] {{ font-size: 16px; font-weight: 650; }}
QLabel[status="success"] {{ color: {STATE_IDLE}; }}
QLabel[status="warning"] {{ color: {STATE_WARNING}; }}
QLabel[status="error"] {{ color: {STATE_ERROR}; }}

QFrame#dialogSurface, QFrame#sectionSurface {{
    background: {APP_SURFACE};
    border: 1px solid {APP_LINE_SOFT};
    border-radius: 14px;
}}
QFrame#historyEntry {{
    background: {APP_SURFACE};
    border: 1px solid {APP_LINE_SOFT};
    border-radius: 11px;
    margin: 2px;
}}
QFrame#historyEntry[highlighted="true"] {{
    background: #373123;
    border-color: rgba(214, 178, 96, 0.50);
}}

QPushButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {APP_SURFACE_RAISED}, stop:1 {APP_SURFACE});
    border: 1px solid {APP_LINE_SOFT};
    border-radius: 9px;
    padding: 7px 12px;
    color: {APP_TEXT};
    min-height: 18px;
}}
QPushButton:hover {{
    background: {APP_SURFACE_HOVER};
    border-color: {APP_LINE_STRONG};
}}
QPushButton#primaryAction {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {BLITZ_300}, stop:0.48 {BLITZ_500}, stop:1 #a57c35);
    color: #1b160c;
    font-weight: 700;
    border-color: rgba(255, 236, 177, 0.64);
}}
QPushButton#primaryAction:disabled {{
    background: {APP_SURFACE_DISABLED};
    color: {APP_TEXT_FAINT};
    border-color: {APP_LINE_SOFT};
}}
QPushButton:pressed {{
    background: {APP_SURFACE_SUNK};
    border-color: rgba(214, 178, 96, 0.28);
}}
QPushButton:focus {{
    border-color: rgba(230, 200, 120, 0.78);
    outline: none;
}}
QPushButton:disabled {{
    color: {APP_TEXT_FAINT};
    background: {APP_SURFACE_DISABLED};
    border-color: rgba(255, 255, 255, 0.04);
}}
QPushButton:checked {{
    background: #3b3424;
    border-color: rgba(214, 178, 96, 0.48);
    color: {BLITZ_300};
}}
QPushButton#iconButton, QPushButton#toolbarButton, QPushButton#goldAction,
QPushButton#panelTrigger {{ padding: 0; min-height: 0; }}
QPushButton#recordButton {{
    background: transparent;
    border: none;
    padding: 0;
    min-width: {RECORD_BUTTON_WIDTH}px;
    max-width: {RECORD_BUTTON_WIDTH}px;
    min-height: {RECORD_BUTTON_HEIGHT}px;
    max-height: {RECORD_BUTTON_HEIGHT}px;
}}
QPushButton#iconButton {{ border-radius: 8px; }}
QPushButton[danger="true"] {{ color: {STATE_ERROR}; }}
QPushButton[success="true"] {{ color: {STATE_IDLE}; }}

QComboBox, QLineEdit, QSpinBox, QPlainTextEdit, QTextEdit, QListWidget {{
    background: {APP_SURFACE_SUNK};
    border: 1px solid {APP_LINE_SOFT};
    border-radius: 9px;
    padding: 7px 9px;
}}
QComboBox:hover, QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover,
QListWidget:hover {{
    border-color: {APP_LINE_STRONG};
}}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus, QListWidget:focus {{
    border-color: rgba(230, 200, 120, 0.70);
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
    background: {APP_SURFACE};
    border: 1px solid {APP_LINE_STRONG};
    border-radius: 10px;
    padding: 4px;
    selection-background-color: #453b27;
    selection-color: {BLITZ_300};
    outline: none;
}}

QTabWidget::pane {{
    background: {APP_SURFACE};
    border: 1px solid {APP_LINE_SOFT};
    border-radius: 12px;
    top: -1px;
}}
QTabBar::tab {{
    background: {APP_SURFACE_SUNK};
    color: {APP_TEXT_DIM};
    padding: 8px 14px;
    border: 1px solid {APP_LINE_SOFT};
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
    background: {APP_SURFACE};
    color: {BLITZ_300};
    border-bottom: 2px solid {BLITZ_500};
}}
QTabBar::tab:hover:!selected {{
    color: {APP_TEXT};
    background: {APP_SURFACE_RAISED};
}}

QCheckBox {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 2px;
    spacing: 8px;
}}
QCheckBox:focus {{
    border-color: rgba(230, 200, 120, 0.70);
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    background: {APP_SURFACE_SUNK};
    border: 1px solid {APP_LINE_STRONG};
    border-radius: 5px;
}}
QCheckBox::indicator:checked {{
    background: {BLITZ_500};
    border-color: {BLITZ_300};
}}

QToolTip {{
    background: {APP_SURFACE_RAISED};
    color: {APP_TEXT};
    border: 1px solid {APP_LINE_STRONG};
    border-radius: 7px;
    padding: 5px 8px;
}}

QMenu {{
    background: {APP_SURFACE};
    border: 1px solid {APP_LINE_STRONG};
    border-radius: 11px;
    padding: 7px;
}}
QMenu::item {{
    background: transparent;
    border-radius: 7px;
    padding: 7px 26px 7px 12px;
}}
QMenu::item:selected {{
    background: {APP_SURFACE_HOVER};
    color: {BLITZ_300};
}}
QMenu::item:disabled {{ color: {APP_TEXT_FAINT}; }}
QMenu::separator {{
    height: 1px;
    background: {APP_LINE_SOFT};
    margin: 6px 9px;
}}
QMenu::indicator:checked {{
    background: {BLITZ_500};
    border-radius: 4px;
}}

QAbstractScrollArea, QAbstractScrollArea::viewport {{
    background: {APP_SURFACE_SUNK};
    border: none;
}}
QScrollArea {{
    border: 1px solid {APP_LINE_SOFT};
    border-radius: 10px;
}}
QScrollBar:vertical, QScrollBar:horizontal {{
    background: transparent;
    width: 8px;
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: #555b62;
    border-radius: 4px;
    min-height: 28px;
    min-width: 28px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0;
    height: 0;
}}
QSplitter::handle {{
    background: {APP_LINE_SOFT};
    width: 2px;
    margin: 8px 5px;
}}
QListWidget::item {{
    border-radius: 6px;
    padding: 5px;
}}
QListWidget::item:selected {{
    background: #453b27;
    color: {BLITZ_300};
}}
QDialogButtonBox {{
    background: transparent;
}}
"""


MAIN_WINDOW_QSS = f"""
QWidget#mainWidgetWindow {{ background: transparent; }}
QFrame#mainPanel {{
    background: qradialgradient(cx:0.32, cy:0.20, radius:1.05,
        stop:0 #30343a, stop:0.58 {APP_SURFACE}, stop:1 #1e2125);
    border: 1px solid {APP_LINE_SOFT};
    border-radius: 18px;
}}
QFrame#dictationPopup {{ background: transparent; border: none; }}
QFrame#popupSurface {{
    background: {APP_SURFACE};
    border: 1px solid {APP_LINE_STRONG};
    border-radius: 14px;
}}
QLabel#panelTitle {{ color: {APP_TEXT_DIM}; font-size: 12px; font-weight: 600; padding-left: 2px; }}
QLabel#statusLabel {{ color: {APP_TEXT}; font-size: 12px; font-weight: 600; }}
QLabel#timerLabel {{ color: {APP_TEXT_DIM}; font-family: monospace; font-size: 12px; }}
QPushButton#windowControl {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 0;
    min-height: {WINDOW_BUTTON_SIZE - 2}px;
    max-height: {WINDOW_BUTTON_SIZE - 2}px;
}}
QPushButton#windowControl:hover {{ background: {APP_SURFACE_HOVER}; border-color: {APP_LINE_SOFT}; }}
QPushButton#windowControl[role="close"]:hover {{
    background: rgba(232, 135, 135, 0.22);
    border-color: rgba(232, 135, 135, 0.36);
}}
QPushButton#toolbarButton, QPushButton#panelTrigger, QPushButton#goldAction {{
    /* QSS min-height would otherwise reset the fixed Python size to 0. */
    min-height: {TOOL_BUTTON_SIZE - 2}px;
    max-height: {TOOL_BUTTON_SIZE - 2}px;
}}
QPushButton#toolbarButton, QPushButton#panelTrigger {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 9px;
    color: {APP_TEXT_DIM};
}}
QPushButton#toolbarButton:hover, QPushButton#panelTrigger:hover {{
    background: {APP_SURFACE_HOVER};
    border-color: {APP_LINE_SOFT};
}}
QPushButton#goldAction {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {BLITZ_300}, stop:0.50 {BLITZ_500}, stop:1 #a57c35);
    border: 1px solid rgba(255, 236, 177, 0.62);
    border-radius: 9px;
}}
QPushButton#goldAction:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #fff0bd, stop:0.50 {BLITZ_400}, stop:1 #bb9145);
}}
QComboBox#popupCombo {{ min-height: 22px; }}
QPushButton#dictationToggle {{ color: {BLITZ_300}; }}
QPushButton#discardButton {{ color: {STATE_ERROR}; }}
"""


def apply_theme(app) -> None:
    """Apply the shared dark-neumorphic theme to the QApplication."""
    app.setStyleSheet(APP_QSS)


def repolish(widget) -> None:
    """Re-evaluate QSS after a dynamic property changes."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_status_role(label, role: str | None) -> None:
    """Apply a semantic status role without embedding colors in feature code."""
    label.setProperty("status", role or "")
    repolish(label)


def create_ui_icon(name: str, color: str = APP_TEXT_DIM, size: int = 22) -> QIcon:
    """Draw a consistent, dependency-free line icon for native controls."""
    scale = 2
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale, scale)
    pen = QPen(QColor(color), 1.8, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    center = size / 2

    if name == "edit":
        painter.drawLine(QPointF(5, 16.5), QPointF(15.8, 5.7))
        painter.drawLine(QPointF(14.2, 4.8), QPointF(17.2, 7.8))
        painter.drawLine(QPointF(4.5, 17.5), QPointF(8, 16.7))
    elif name == "history":
        painter.drawArc(QRectF(4, 4, 14, 14), 35 * 16, 292 * 16)
        painter.drawLine(QPointF(4.3, 5.2), QPointF(4.3, 9))
        painter.drawLine(QPointF(4.3, 5.2), QPointF(8, 5.2))
        painter.drawLine(QPointF(center, 7), QPointF(center, center + .5))
        painter.drawLine(QPointF(center, center + .5), QPointF(14.5, 13))
    elif name == "speaker":
        path = QPainterPath(QPointF(4, 9))
        path.lineTo(8, 9)
        path.lineTo(12, 5.5)
        path.lineTo(12, 16.5)
        path.lineTo(8, 13)
        path.lineTo(4, 13)
        path.closeSubpath()
        painter.drawPath(path)
        painter.drawArc(QRectF(11, 7, 7, 8), -55 * 16, 110 * 16)
        painter.drawArc(QRectF(10, 4.5, 11, 13), -52 * 16, 104 * 16)
    elif name == "settings":
        painter.drawEllipse(QRectF(center - 2.4, center - 2.4, 4.8, 4.8))
        painter.drawEllipse(QRectF(center - 6, center - 6, 12, 12))
        for dx, dy in ((0, -8), (0, 8), (-8, 0), (8, 0),
                       (-5.7, -5.7), (5.7, 5.7), (-5.7, 5.7), (5.7, -5.7)):
            start = QPointF(center + dx * .73, center + dy * .73)
            end = QPointF(center + dx, center + dy)
            painter.drawLine(start, end)
    elif name == "more":
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        for x in (6, center, size - 6):
            painter.drawEllipse(QPointF(x, center), 1.4, 1.4)
    elif name == "minimize":
        painter.drawLine(QPointF(size * .28, center), QPointF(size * .72, center))
    elif name == "close":
        near, far = size * .3, size * .7
        painter.drawLine(QPointF(near, near), QPointF(far, far))
        painter.drawLine(QPointF(near, far), QPointF(far, near))
    elif name == "copy":
        painter.drawRoundedRect(QRectF(7, 5, 10, 12), 2, 2)
        painter.drawRoundedRect(QRectF(4, 8, 10, 11), 2, 2)
    elif name == "delete":
        painter.drawLine(QPointF(6, 7), QPointF(16, 7))
        painter.drawLine(QPointF(9, 4.5), QPointF(13, 4.5))
        painter.drawRoundedRect(QRectF(7, 7, 8, 11), 1.5, 1.5)
        painter.drawLine(QPointF(10, 10), QPointF(10, 15))
        painter.drawLine(QPointF(12.5, 10), QPointF(12.5, 15))
    elif name == "check":
        painter.drawLine(QPointF(5, 11), QPointF(9, 15))
        painter.drawLine(QPointF(9, 15), QPointF(17, 7))
    elif name in {"previous", "next"}:
        direction = -1 if name == "previous" else 1
        painter.drawLine(
            QPointF(center + direction * 3, 6),
            QPointF(center - direction * 3, center),
        )
        painter.drawLine(
            QPointF(center - direction * 3, center),
            QPointF(center + direction * 3, size - 6),
        )

    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return QIcon(pixmap)


def _svg_path_points(d: str) -> list[tuple[float, float]]:
    """Parse a single straight-line SVG subpath (M/L/H/V/Z, absolute or relative)."""
    tokens = re.findall(r"[A-Za-z]|-?(?:\d+\.?\d*|\.\d+)", d)
    points: list[tuple[float, float]] = []
    x = y = 0.0
    command = ""
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.isalpha():
            command = token
            index += 1
            if command in "Zz":
                break
            continue
        relative = command.islower()
        kind = command.upper()
        if kind in ("M", "L"):
            dx, dy = float(tokens[index]), float(tokens[index + 1])
            index += 2
            x, y = (x + dx, y + dy) if relative else (dx, dy)
            if kind == "M":
                # Further coordinate pairs after a moveto are implicit linetos.
                command = "l" if relative else "L"
        elif kind in ("H", "V"):
            value = float(tokens[index])
            index += 1
            if kind == "H":
                x = x + value if relative else value
            else:
                y = y + value if relative else value
        else:
            raise ValueError(f"unsupported SVG path command: {command!r}")
        points.append((x, y))
    return points


@lru_cache(maxsize=1)
def _brand_bolt_geometry() -> tuple[tuple[float, ...], tuple[tuple[float, float], ...]]:
    """Capsule rect and bolt polygon of the official mark, in SVG units."""
    try:
        ns = "{http://www.w3.org/2000/svg}"
        root = ET.parse(BRAND_MARK_SVG).getroot()
        rect = root.find(f"{ns}rect")
        bolt = next(path for path in root.iter(f"{ns}path")
                    if path.get("fill", "").lower() == _BRAND_BOLT_FILL)
        capsule = tuple(float(rect.get(key)) for key in ("x", "y", "width", "height"))
        points = _svg_path_points(bolt.get("d"))
    except (OSError, ET.ParseError, StopIteration, AttributeError,
            TypeError, ValueError, IndexError):
        capsule, points = _BRAND_CAPSULE_FALLBACK, _svg_path_points(_BRAND_BOLT_FALLBACK)
    return capsule, tuple(points)


def brand_bolt_path(capsule: QRectF) -> QPainterPath:
    """Official Blitztext bolt placed in ``capsule`` like in the logo's microphone.

    One uniform scale (capsule width to logo capsule width) keeps the original
    angles and the bolt-to-capsule proportion; the bolt stays centered.
    """
    (logo_x, logo_y, logo_w, logo_h), points = _brand_bolt_geometry()
    scale = capsule.width() / logo_w
    origin_x, origin_y = logo_x + logo_w / 2, logo_y + logo_h / 2
    center = capsule.center()
    path = QPainterPath()
    path.addPolygon(QPolygonF([
        QPointF(center.x() + (x - origin_x) * scale, center.y() + (y - origin_y) * scale)
        for x, y in points
    ]))
    path.closeSubpath()
    return path


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
    """Fallback icon drawn in the shared dark-neumorphic palette."""
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

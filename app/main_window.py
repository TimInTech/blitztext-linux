"""Neumorphic Blitztext desktop widget with transient secondary controls."""
from __future__ import annotations

import math
import time
from typing import Optional

from PyQt6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, pyqtSlot
from PyQt6.QtGui import (QBrush, QCloseEvent, QColor, QConicalGradient,
                         QEnterEvent, QKeySequence, QLinearGradient,
                         QMouseEvent, QPainter, QPainterPath, QPen,
                         QRadialGradient)
from PyQt6.QtWidgets import (QApplication, QComboBox, QFrame,
                             QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                             QLayout, QPushButton, QVBoxLayout, QWidget)

from app import theme
from app.i18n import t
from app.llm_service import WorkflowType
from app.writing_presets import CUSTOM_PRESET_KEY, WRITING_PRESET_KEYS

_WORKFLOW_ORDER = [
    WorkflowType.TRANSCRIPTION,
    WorkflowType.LOCAL,
    WorkflowType.TEXT_IMPROVER,
    WorkflowType.DAMPF_ABLASSEN,
    WorkflowType.EMOJI_TEXT,
]

# RecordButton geometry, relative to the widget center. Face and microphone
# artwork keep their design coordinates and are scaled to _FACE_DIAMETER.
_ART_DIAMETER = 98
_FACE_DIAMETER = 80
_ART_SCALE = _FACE_DIAMETER / _ART_DIAMETER
_RING_DIAMETER = 92
_RING_PEN = 4
_WAVE_BARS = 5
_WAVE_PITCH = 6
_WAVE_WIDTH = 3.0
_WAVE_CLEARANCE = 52  # first bar sits just outside the processing ring
_WAVE_MAX_HEIGHT = 28

# Microphone capsule in design coordinates. The official logo bolt is cut out
# of it, so the dark face shows through as part of the microphone.
_MIC_CAPSULE = QRectF(-11, -31, 22, 49)


def _mic_body_path() -> QPainterPath:
    body = QPainterPath()
    body.addRoundedRect(_MIC_CAPSULE, 11, 11)
    return body.subtracted(theme.brand_bolt_path(_MIC_CAPSULE))


_MIC_BODY = _mic_body_path()

# Main window: a single frameless surface holds header, microphone, status and
# tools. The window margins only reserve the measured reach of its shadow.
_SHADOW_MARGINS = (10, 6, 10, 14)  # left, top, right, bottom
_PANEL_PADDING = (10, 6, 10, 10)  # plus the 1 px QSS border
_TOOL_GAP = 6
_TOOLBAR_TOP_GAP = 8
_HISTORY_BUTTON_WIDTH = 48


def _shadow(widget: QWidget, blur: float, y: float, alpha: int) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, y)
    effect.setColor(QColor(5, 6, 8, alpha))
    widget.setGraphicsEffect(effect)


class RecordButton(QPushButton):
    """Gold microphone button with recording waves and a processing ring."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._mode = "IDLE"
        self._phase = 0.0
        self._hovered = False
        self._pressed = False
        self.setObjectName("recordButton")
        self.setFixedSize(theme.RECORD_BUTTON_WIDTH, theme.RECORD_BUTTON_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self._anim = QTimer(self)
        self._anim.setInterval(40)
        self._anim.timeout.connect(self._tick)

    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> None:
        self._mode = mode if mode in ("IDLE", "RECORDING", "PROCESSING") else "IDLE"
        if self._mode in ("RECORDING", "PROCESSING"):
            if not self._anim.isActive():
                self._anim.start()
        else:
            self._anim.stop()
            self._phase = 0.0
        self.update()

    def _tick(self) -> None:
        # 0.03 per 40 ms: one calm cycle every ~1.3 s.
        self._phase = (self._phase + 0.03) % 1.0
        self.update()

    def _center(self) -> QPointF:
        return QPointF(self.width() / 2, self.height() / 2)

    def hitButton(self, pos: QPoint) -> bool:  # noqa: N802
        """Only the round microphone toggles; the wave areas are decoration."""
        center = self._center()
        return math.hypot(pos.x() - center.x(), pos.y() - center.y()) <= _RING_DIAMETER / 2

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # Presses beside the microphone are ignored by Qt and move the window.
        self._pressed = self.hitButton(event.position().toPoint())
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # PyQt6 only accepts QPointF here; a TypeError in paintEvent aborts the app.
        center = self._center()
        if self._mode == "RECORDING":
            self._draw_waves(painter, center)

        radius = _FACE_DIAMETER / 2
        circle = QRectF(center.x() - radius, center.y() - radius, _FACE_DIAMETER, _FACE_DIAMETER)
        shadow_offset = 2 if self._pressed else 5
        painter.setPen(QPen(QColor(4, 5, 6, 165), 5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(circle.translated(2, shadow_offset))
        rim = QLinearGradient(circle.topLeft(), circle.bottomRight())
        for stop, color in ((0, "#fff0bd"), (.24, "#c8aa68"), (.62, "#625337"), (1, "#e0c17e")):
            rim.setColorAt(stop, QColor(color))
        painter.setPen(QPen(QBrush(rim), 2))
        face = QRadialGradient(center.x() - 13 * _ART_SCALE, center.y() - 25 * _ART_SCALE,
                               83 * _ART_SCALE)
        face_colors = (
            ((0, "#474a4e"), (.52, "#303338"), (1, "#1a1c1f"))
            if self._hovered
            else ((0, "#3b3e43"), (.52, "#282b2f"), (1, "#17191b"))
        )
        for stop, color in face_colors:
            face.setColorAt(stop, QColor(color))
        painter.setBrush(QBrush(face))
        painter.drawEllipse(circle)
        painter.setPen(QPen(QColor(255, 255, 255, 20), 1))
        painter.drawEllipse(circle.adjusted(3, 3, -3, -3))

        if self._mode == "PROCESSING":
            progress = QConicalGradient(center, -90 - self._phase * 360)
            progress.setColorAt(0, QColor("#ffe6a1"))
            progress.setColorAt(.70, QColor("#b28b43"))
            progress.setColorAt(.71, QColor(178, 139, 67, 20))
            progress.setColorAt(1, QColor(178, 139, 67, 20))
            painter.setPen(QPen(QBrush(progress), _RING_PEN, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            ring_radius = _RING_DIAMETER / 2
            painter.drawArc(QRectF(center.x() - ring_radius, center.y() - ring_radius,
                                   _RING_DIAMETER, _RING_DIAMETER), 0, 360 * 16)
        self._draw_mic(painter, center)

    def _draw_waves(self, painter: QPainter, center: QPointF) -> None:
        """Mirrored gold level bars rippling outward beside the microphone."""
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(_WAVE_BARS):
            offset = _WAVE_CLEARANCE + index * _WAVE_PITCH
            envelope = 1.0 - index / _WAVE_BARS
            swing = 0.5 + 0.5 * math.sin(self._phase * math.tau - index * 0.85)
            height = 4 + (_WAVE_MAX_HEIGHT - 4) * envelope * (0.35 + 0.65 * swing)
            painter.setBrush(QColor(240, 199, 105, 235 - index * 18))
            for x in (center.x() - offset, center.x() + offset):
                painter.drawRoundedRect(
                    QRectF(x - _WAVE_WIDTH / 2, center.y() - height / 2, _WAVE_WIDTH, height),
                    _WAVE_WIDTH / 2, _WAVE_WIDTH / 2,
                )
        painter.restore()

    def _draw_mic(self, painter: QPainter, center: QPointF) -> None:
        painter.save()
        painter.translate(center)
        painter.scale(_ART_SCALE, _ART_SCALE)
        gold =QLinearGradient(-12, -30, 16, 41)
        for stop, color in ((0, "#fff1ba"), (.28, "#f2d68d"), (.53, "#a98240"),
                            (.76, "#f7dc91"), (1, "#8d6934")):
            gold.setColorAt(stop, QColor(color))
        brush = QBrush(gold)
        painter.setPen(QPen(QColor("#fce8ae"), 1.1))
        painter.setBrush(brush)
        painter.drawPath(_MIC_BODY)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(brush, 5.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawArc(QRectF(-20, -8, 40, 40), 180 * 16, 180 * 16)
        painter.drawLine(0, 31, 0, 41)
        painter.drawLine(-12, 41, 12, 41)
        painter.restore()


class DictationPopup(QFrame):
    def __init__(self, owner: "MainWindow") -> None:
        super().__init__(owner, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setObjectName("dictationPopup")
        self.setFixedWidth(248)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


class MainWindow(QWidget):
    """One frameless surface with header, microphone, status and tools.

    Secondary options stay in a transient popup and never enlarge the surface.
    """

    def __init__(self, controller, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._state = "IDLE"
        self._rec_start: Optional[float] = None
        self.setWindowTitle(t("app.name"))
        # The panel draws its own title and window controls.
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("mainWidgetWindow")
        self.setStyleSheet(self._qss())
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_timer_label)
        self._setup_ui()
        self.update_state("IDLE", None, None)

    @staticmethod
    def _qss() -> str:
        return theme.MAIN_WINDOW_QSS

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(*_SHADOW_MARGINS)
        root.setSpacing(0)
        # Size the native window from its visible surface instead of a fixed guess.
        root.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        self._main_panel = QFrame(self)
        self._main_panel.setObjectName("mainPanel")
        _shadow(self._main_panel, 14, 4, 150)
        panel = QVBoxLayout(self._main_panel)
        panel.setContentsMargins(*_PANEL_PADDING)
        panel.setSpacing(0)

        header = QHBoxLayout()
        header.setSpacing(2)
        self._title_label = QLabel(self.windowTitle(), self._main_panel)
        self._title_label.setObjectName("panelTitle")
        self.windowTitleChanged.connect(self._title_label.setText)
        header.addWidget(self._title_label)
        header.addStretch(1)
        self._btn_minimize = self._window_button(
            "minimize", t("mainwindow.tooltip.minimize"), self.showMinimized
        )
        header.addWidget(self._btn_minimize)
        self._btn_close = self._window_button(
            "close", t("mainwindow.tooltip.close"), self.close
        )
        self._btn_close.setProperty("role", "close")
        header.addWidget(self._btn_close)
        panel.addLayout(header)

        self._btn_toggle = RecordButton(self._main_panel)
        self._btn_toggle.clicked.connect(self._on_toggle_clicked)
        panel.addWidget(self._btn_toggle, 0, Qt.AlignmentFlag.AlignHCenter)
        status = QHBoxLayout()
        status.setSpacing(6)
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rec_indicator = QLabel("●")
        status.addWidget(self._rec_indicator)
        self._status_label = QLabel(t("mainwindow.status.ready"))
        self._status_label.setObjectName("statusLabel")
        status.addWidget(self._status_label)
        self._timer_label = QLabel("00:00")
        self._timer_label.setObjectName("timerLabel")
        status.addWidget(self._timer_label)
        panel.addLayout(status)
        panel.addSpacing(_TOOLBAR_TOP_GAP)

        # The tool row is part of the same surface; its width sets the panel width.
        tools = QHBoxLayout()
        tools.setSpacing(_TOOL_GAP)
        self._btn_edit_text = self._toolbar_button(
            "edit", t("mainwindow.tooltip.edit_text"),
            self._controller.show_compose_window, accent=True,
        )
        self._btn_edit_text.setAccessibleName(t("mainwindow.button.edit_text"))
        self._btn_edit_text.setShortcut(QKeySequence("Ctrl+E"))
        self._btn_history = self._toolbar_button(
            "history", t("mainwindow.button.history").format(count=0),
            self._controller.show_history_panel, width=_HISTORY_BUTTON_WIDTH,
            text="0",
        )
        self._btn_tts = self._toolbar_button(
            "speaker", t("mainwindow.tooltip.tts"), self._controller.show_tts_window
        )
        self._btn_settings = self._toolbar_button(
            "settings", t("mainwindow.tooltip.settings"),
            self._controller.show_settings_dialog
        )
        self._btn_options = self._toolbar_button(
            "more", t("mainwindow.tooltip.more"), self._show_options_popup
        )
        self._btn_options.setObjectName("panelTrigger")
        for button in (
            self._btn_edit_text, self._btn_history, self._btn_tts,
            self._btn_settings, self._btn_options,
        ):
            tools.addWidget(button)
        panel.addLayout(tools)
        root.addWidget(self._main_panel)
        self._setup_options_popup()

    def _toolbar_button(
        self, icon_name: str, tooltip: str, callback, *, width: int = theme.TOOL_BUTTON_SIZE,
        accent: bool = False, text: str = "",
    ) -> QPushButton:
        button = QPushButton(text, self._main_panel)
        button.setObjectName("goldAction" if accent else "toolbarButton")
        icon_color = "#2b210e" if accent else theme.APP_TEXT_DIM
        button.setIcon(theme.create_ui_icon(icon_name, icon_color, theme.TOOL_ICON_SIZE))
        button.setIconSize(QSize(theme.TOOL_ICON_SIZE, theme.TOOL_ICON_SIZE))
        button.setFixedSize(width, theme.TOOL_BUTTON_SIZE)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        button.clicked.connect(callback)
        return button

    def _window_button(self, icon_name: str, tooltip: str, callback) -> QPushButton:
        button = QPushButton(self._main_panel)
        button.setObjectName("windowControl")
        button.setIcon(theme.create_ui_icon(icon_name, theme.APP_TEXT_DIM, 14))
        button.setIconSize(QSize(14, 14))
        button.setFixedSize(theme.WINDOW_BUTTON_SIZE, theme.WINDOW_BUTTON_SIZE)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        button.clicked.connect(lambda _checked=False: callback())
        return button

    def _setup_options_popup(self) -> None:
        self._options_popup = DictationPopup(self)
        outer = QVBoxLayout(self._options_popup)
        outer.setContentsMargins(16, 16, 16, 20)
        self._popup_surface = QFrame(self._options_popup)
        self._popup_surface.setObjectName("popupSurface")
        _shadow(self._popup_surface, 30, 8, 185)
        outer.addWidget(self._popup_surface)
        popup = QVBoxLayout(self._popup_surface)
        popup.setContentsMargins(12, 12, 12, 12)
        popup.setSpacing(8)
        self._workflow_combo = QComboBox(self._popup_surface)
        self._workflow_combo.setObjectName("popupCombo")
        for workflow in _WORKFLOW_ORDER:
            self._workflow_combo.addItem(t(f"workflow.{workflow.value}.name"), userData=workflow)
        self._workflow_combo.currentIndexChanged.connect(self._on_workflow_changed)
        popup.addWidget(self._workflow_combo)
        self._preset_combo = QComboBox(self._popup_surface)
        self._preset_combo.setObjectName("popupCombo")
        for key in WRITING_PRESET_KEYS:
            if key == CUSTOM_PRESET_KEY:
                self._preset_combo.insertSeparator(self._preset_combo.count())
            self._preset_combo.addItem(t(f"preset.{key}.name"), userData=key)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self._preset_combo.hide()
        popup.addWidget(self._preset_combo)
        self._btn_prompt = QPushButton(t("compose.custom.edit"), self._popup_surface)
        self._btn_prompt.setObjectName("promptButton")
        self._btn_prompt.clicked.connect(self._edit_prompt)
        self._btn_prompt.hide()
        popup.addWidget(self._btn_prompt)
        self._btn_dictation = QPushButton(t("mainwindow.button.dictation"), self._popup_surface)
        self._btn_dictation.setObjectName("dictationToggle")
        self._btn_dictation.setCheckable(True)
        self._btn_dictation.clicked.connect(self._on_dictation_clicked)
        popup.addWidget(self._btn_dictation)
        self._btn_discard = QPushButton(t("mainwindow.button.discard"), self._popup_surface)
        self._btn_discard.setObjectName("discardButton")
        self._btn_discard.setEnabled(False)
        self._btn_discard.clicked.connect(self._on_discard_clicked)
        popup.addWidget(self._btn_discard)
        self._options_popup.adjustSize()
        self._options_popup.hide()

    def _show_options_popup(self) -> None:
        self._options_popup.adjustSize()
        anchor = self._btn_options.mapToGlobal(QPoint(self._btn_options.width(), 0))
        position = QPoint(anchor.x() - self._options_popup.width(), anchor.y() - self._options_popup.height() - 4)
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            position.setX(max(area.left() + 6, min(position.x(), area.right() - self._options_popup.width() - 6)))
            position.setY(max(area.top() + 6, min(position.y(), area.bottom() - self._options_popup.height() - 6)))
        self._options_popup.move(position)
        self._options_popup.show()
        self._options_popup.raise_()

    def _selected_workflow(self) -> WorkflowType:
        workflow = self._workflow_combo.currentData()
        return workflow if isinstance(workflow, WorkflowType) else WorkflowType.TRANSCRIPTION

    @pyqtSlot()
    def _on_workflow_changed(self) -> None:
        visible = self._selected_workflow() == WorkflowType.TEXT_IMPROVER
        self._preset_combo.setVisible(visible)
        self._btn_prompt.setVisible(visible)
        self._options_popup.adjustSize()

    def _edit_prompt(self) -> None:
        self._options_popup.hide()
        self._controller.show_custom_prompt()

    @pyqtSlot()
    def _on_preset_changed(self) -> None:
        key = self._preset_combo.currentData()
        if key:
            self._controller.main_window_preset_changed(key)

    @pyqtSlot()
    def _on_toggle_clicked(self) -> None:
        self._controller.gui_toggle_recording(self._selected_workflow())

    @pyqtSlot()
    def _on_discard_clicked(self) -> None:
        self._options_popup.hide()
        self._controller.gui_discard()

    @pyqtSlot()
    def _on_dictation_clicked(self) -> None:
        self._update_dictation_text()
        self._controller.set_dictation_mode(self._btn_dictation.isChecked())

    def update_state(self, state: str, workflow: Optional[WorkflowType], error: Optional[str]) -> None:
        self._state = state
        recording = state == "RECORDING"
        busy = state in ("TRANSCRIBING", "LLM_REWRITING")
        self._btn_toggle.setText("Stopp" if recording else "Start")
        self._btn_toggle.setEnabled(state in ("IDLE", "RECORDING"))
        self._btn_toggle.set_mode("RECORDING" if recording else "PROCESSING" if busy else "IDLE")
        self._btn_discard.setEnabled(recording)
        for control in (self._workflow_combo, self._preset_combo, self._btn_prompt):
            control.setEnabled(state == "IDLE")
        if error:
            self._set_status(t("mainwindow.status.error"), theme.STATE_ERROR)
        elif recording:
            self._set_status(t("mainwindow.status.recording"), theme.STATE_RECORDING)
        elif state == "TRANSCRIBING":
            self._set_status(t("mainwindow.status.transcribing"), theme.STATE_PROCESSING)
        elif state == "LLM_REWRITING":
            self._set_status(t("mainwindow.status.processing"), theme.STATE_PROCESSING)
        else:
            self._set_status(t("mainwindow.status.ready"), theme.STATE_IDLE)
        self._timer_label.setVisible(not busy and not error)
        if recording:
            if self._rec_start is None:
                self._rec_start = time.monotonic()
                self._update_timer_label()
                self._timer.start()
        else:
            self._timer.stop()
            self._rec_start = None
            self._timer_label.setText("00:00")
        if workflow is not None:
            self._select_workflow(workflow)

    def _select_workflow(self, workflow: WorkflowType) -> None:
        for index in range(self._workflow_combo.count()):
            if self._workflow_combo.itemData(index) == workflow:
                self._workflow_combo.blockSignals(True)
                self._workflow_combo.setCurrentIndex(index)
                self._workflow_combo.blockSignals(False)
                self._on_workflow_changed()
                return

    def _set_status(self, text: str, color: str) -> None:
        self._status_label.setText(text)
        self._rec_indicator.setStyleSheet(f"color: {color}; font-size: 11px;")

    def set_history_count(self, count: int) -> None:
        label = t("mainwindow.button.history").format(count=count)
        self._btn_history.setText(str(count))
        self._btn_history.setToolTip(label)
        self._btn_history.setAccessibleName(label)

    def set_dictation_checked(self, checked: bool) -> None:
        self._btn_dictation.blockSignals(True)
        self._btn_dictation.setChecked(checked)
        self._btn_dictation.blockSignals(False)
        self._update_dictation_text()

    def _update_dictation_text(self) -> None:
        key = (
            "mainwindow.button.dictation_active"
            if self._btn_dictation.isChecked()
            else "mainwindow.button.dictation"
        )
        self._btn_dictation.setText(t(key))

    def set_preset(self, key: str) -> None:
        self._preset_combo.blockSignals(True)
        for index in range(self._preset_combo.count()):
            if self._preset_combo.itemData(index) == key:
                self._preset_combo.setCurrentIndex(index)
                break
        self._preset_combo.blockSignals(False)

    def _update_timer_label(self) -> None:
        if self._rec_start is not None:
            elapsed = int(time.monotonic() - self._rec_start)
            self._timer_label.setText(f"{elapsed // 60:02d}:{elapsed % 60:02d}")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """Move the frameless window from any non-interactive part of the panel."""
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.windowHandle()
            # The compositor performs the move; required on Wayland.
            if handle is not None and handle.startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._options_popup.hide()
        event.ignore()
        self.hide()

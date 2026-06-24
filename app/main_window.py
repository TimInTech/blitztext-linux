"""Hauptfenster fuer BlitztextLinux (Glass-Redesign).

Grafischer Fallback zum globalen Hotkey: Start/Stopp per Maus-Klick,
Workflow-Auswahl, Verwerfen, Diktat, Verlauf, Vorlesen und Einstellungen.

Das Design folgt dem Blitztext Design System (Glass-Idiom): runder Amber-
Record-„Shutter" als Hero, Status-Punkt + Timer, weiche Pill-Buttons fuer
Verwerfen/Diktat und runde Icon-Buttons fuer Vorlesen/Einstellungen.

Das Fenster ist rein praesentational — die gesamte Aufnahme-/State-Logik
bleibt im Controller (`BlitztextApp`). Beim Schliessen wird es nur versteckt,
die App laeuft im Tray weiter.
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QRectF
from PyQt6.QtGui import QBrush, QCloseEvent, QColor, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.llm_service import WorkflowType, LLM_WORKFLOWS
from app.i18n import t
from app import theme
from app.writing_presets import WRITING_PRESET_KEYS

# Reihenfolge der Workflows in der Auswahl
_WORKFLOW_ORDER = [
    WorkflowType.TRANSCRIPTION,
    WorkflowType.LOCAL,
    WorkflowType.TEXT_IMPROVER,
    WorkflowType.DAMPF_ABLASSEN,
    WorkflowType.EMOJI_TEXT,
]


class RecordButton(QPushButton):
    """Runder Aufnahme-„Shutter" im Glass-Idiom.

    Zeichnet einen Mikrofon-/Stop-/Spinner-Glyph auf einer amberfarbenen
    bzw. roten Kreisflaeche. Der Text (`Start`/`Stopp`) bleibt gesetzt, wird
    aber nicht gemalt — so bleibt `text()` fuer Tests/Logik nutzbar.
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._mode = "IDLE"  # IDLE | RECORDING | PROCESSING
        self._phase = 0.0
        self.setFixedSize(68, 68)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)

        self._anim = QTimer(self)
        self._anim.setInterval(60)
        self._anim.timeout.connect(self._tick)

    def set_mode(self, mode: str) -> None:
        if mode not in ("IDLE", "RECORDING", "PROCESSING"):
            mode = "IDLE"
        self._mode = mode
        if mode in ("RECORDING", "PROCESSING"):
            if not self._anim.isActive():
                self._anim.start()
        else:
            self._anim.stop()
            self._phase = 0.0
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.08) % 1.0
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt naming)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        size = min(self.width(), self.height())
        margin = 6
        d = size - 2 * margin
        rect = QRectF(margin, margin, d, d)
        cx, cy = self.width() / 2, self.height() / 2

        if self._mode == "RECORDING":
            base, hi = QColor("#c62828"), QColor("#e04545")
        elif self._mode == "PROCESSING":
            base, hi = QColor("#262a31"), QColor("#383e46")
        else:
            base, hi = QColor(theme.BLITZ_500), QColor("#edbe35")

        grad = QRadialGradient(cx, margin + d * 0.32, d)
        grad.setColorAt(0.0, hi)
        grad.setColorAt(1.0, base)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(rect)

        # Feiner innerer Highlight-Ring statt grossflaechigem Glanz
        p.setPen(QPen(QColor(255, 255, 255, 36), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))

        # Pulsierender Ring waehrend der Aufnahme (die eine bewusste Animation)
        if self._mode == "RECORDING":
            spread = margin * self._phase
            ring = QRectF(margin - spread, margin - spread,
                          d + 2 * spread, d + 2 * spread)
            alpha = int(150 * (1.0 - self._phase))
            p.setPen(QPen(QColor(229, 72, 72, alpha), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(ring)

        p.translate(cx, cy)
        if self._mode == "RECORDING":
            self._draw_stop(p)
        elif self._mode == "PROCESSING":
            self._draw_spinner(p)
        else:
            self._draw_mic(p, QColor("#3a2a04"))
        p.end()

    def _draw_mic(self, p: QPainter, color: QColor) -> None:
        p.setPen(QPen(color, 2.2, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(QBrush(color))
        p.drawRoundedRect(QRectF(-4.5, -11.5, 9, 15), 4.5, 4.5)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(-8, -6, 16, 15).toRect(), 200 * 16, 140 * 16)
        p.drawLine(0, 7, 0, 12)
        p.drawLine(-5, 12, 5, 12)

    def _draw_stop(self, p: QPainter) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawRoundedRect(QRectF(-8.5, -8.5, 17, 17), 5, 5)

    def _draw_spinner(self, p: QPainter) -> None:
        p.setPen(QPen(QColor(255, 255, 255, 60), 3, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(-12, -12, 24, 24))
        p.setPen(QPen(QColor("#ffffff"), 3, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap))
        start = int(-self._phase * 360 * 16)
        p.drawArc(QRectF(-12, -12, 24, 24).toRect(), start, 90 * 16)


class MainWindow(QWidget):
    """Klickbare Oberflaeche fuer Aufnahme-Steuerung und Komfort-Funktionen."""

    def __init__(self, controller, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._state = "IDLE"
        self._rec_start: Optional[float] = None

        self.setWindowTitle(t("app.name"))
        self.setFixedWidth(256)
        self.resize(256, 232)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_timer_label)

        self._setup_ui()
        self.update_state("IDLE", None, None)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        # Workflow-Auswahl (Karten-Pill)
        self._workflow_combo = QComboBox()
        self._workflow_combo.setMinimumHeight(28)
        for wf in _WORKFLOW_ORDER:
            self._workflow_combo.addItem(t(f"workflow.{wf.value}.name"), userData=wf)
        self._workflow_combo.currentIndexChanged.connect(self._on_workflow_changed)
        layout.addWidget(self._workflow_combo)

        # Schreibstil-Preset-Auswahl (nur sichtbar bei Blitztext+)
        self._preset_combo = QComboBox()
        self._preset_combo.setMinimumHeight(28)
        for key in WRITING_PRESET_KEYS:
            self._preset_combo.addItem(t(f"preset.{key}.name"), userData=key)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self._preset_combo.setVisible(False)
        layout.addWidget(self._preset_combo)

        # Hero: runder Record-Shutter
        self._btn_toggle = RecordButton()
        self._btn_toggle.clicked.connect(self._on_toggle_clicked)
        hero_row = QHBoxLayout()
        hero_row.addStretch()
        hero_row.addWidget(self._btn_toggle)
        hero_row.addStretch()
        layout.addLayout(hero_row)

        # Statuszeile: Punkt + Text + Timer in einer kompakten Zeile
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        status_row.addStretch()
        self._rec_indicator = QLabel("●")
        self._rec_indicator.setStyleSheet(f"color: {theme.STATE_IDLE}; font-size: 10px;")
        status_row.addWidget(self._rec_indicator)
        self._status_label = QLabel(t("mainwindow.status.ready"))
        self._status_label.setStyleSheet("font-size: 12px; font-weight: 600;")
        status_row.addWidget(self._status_label)
        self._timer_label = QLabel("00:00")
        self._timer_label.setStyleSheet(
            "font-size: 12px; font-family: monospace; font-weight: 600; "
            f"color: {theme.APP_TEXT_FAINT};"
        )
        status_row.addWidget(self._timer_label)
        status_row.addStretch()
        layout.addLayout(status_row)

        # Sekundaerzeile: Verwerfen + Diktat (Pills)
        sec_row = QHBoxLayout()
        sec_row.setSpacing(6)
        self._btn_discard = QPushButton(t("mainwindow.button.discard"))
        self._btn_discard.setMinimumHeight(28)
        self._btn_discard.setStyleSheet("border-radius: 14px; font-weight: 600;")
        self._btn_discard.setEnabled(False)
        self._btn_discard.clicked.connect(self._on_discard_clicked)
        sec_row.addWidget(self._btn_discard)

        self._btn_dictation = QPushButton(t("mainwindow.button.dictation"))
        self._btn_dictation.setMinimumHeight(28)
        self._btn_dictation.setStyleSheet("border-radius: 14px; font-weight: 600;")
        self._btn_dictation.setCheckable(True)
        self._btn_dictation.clicked.connect(self._on_dictation_clicked)
        sec_row.addWidget(self._btn_dictation)
        layout.addLayout(sec_row)

        # Unterzeile: Verlauf (mit Zaehler), Vorlesen, Einstellungen
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(6)
        self._btn_history = QPushButton(t("mainwindow.button.history").format(count=0))
        self._btn_history.setMinimumHeight(28)
        self._btn_history.setStyleSheet(f"border-radius: 14px; color: {theme.APP_TEXT_DIM};")
        self._btn_history.clicked.connect(self._controller.show_history_panel)
        bottom_row.addWidget(self._btn_history, 1)

        self._btn_tts = QPushButton("♪")
        self._btn_tts.setFixedSize(28, 28)
        self._btn_tts.setStyleSheet(
            f"border-radius: 14px; font-size: 13px; color: {theme.APP_TEXT_DIM}; padding: 0;"
        )
        self._btn_tts.setToolTip(t("mainwindow.tooltip.tts"))
        self._btn_tts.clicked.connect(self._controller.show_tts_window)
        bottom_row.addWidget(self._btn_tts)

        self._btn_settings = QPushButton("⚙︎")
        self._btn_settings.setFixedSize(28, 28)
        self._btn_settings.setStyleSheet(
            f"border-radius: 14px; font-size: 13px; color: {theme.APP_TEXT_DIM}; padding: 0;"
        )
        self._btn_settings.setToolTip(t("mainwindow.tooltip.settings"))
        self._btn_settings.clicked.connect(self._controller.show_settings_dialog)
        bottom_row.addWidget(self._btn_settings)
        layout.addLayout(bottom_row)

    # ------------------------------------------------------------------
    # Aktionen
    # ------------------------------------------------------------------

    def _selected_workflow(self) -> WorkflowType:
        wf = self._workflow_combo.currentData()
        return wf if isinstance(wf, WorkflowType) else WorkflowType.TRANSCRIPTION

    @pyqtSlot()
    def _on_workflow_changed(self) -> None:
        is_text_improver = self._selected_workflow() == WorkflowType.TEXT_IMPROVER
        self._preset_combo.setVisible(is_text_improver)
        self.adjustSize()

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
        self._controller.gui_discard()

    @pyqtSlot()
    def _on_dictation_clicked(self) -> None:
        self._controller.set_dictation_mode(self._btn_dictation.isChecked())

    # ------------------------------------------------------------------
    # Vom Controller aufgerufen
    # ------------------------------------------------------------------

    def update_state(self, state: str, workflow: Optional[WorkflowType], error: Optional[str]) -> None:
        self._state = state
        recording = state == "RECORDING"
        busy = state in ("TRANSCRIBING", "LLM_REWRITING")

        # Text bleibt fuer Tests/Logik gesetzt; der Shutter malt den Glyph.
        self._btn_toggle.setText("Stopp" if recording else "Start")
        self._btn_toggle.setEnabled(state in ("IDLE", "RECORDING"))
        self._btn_toggle.set_mode(
            "RECORDING" if recording else ("PROCESSING" if busy else "IDLE")
        )
        self._btn_discard.setEnabled(recording)
        self._workflow_combo.setEnabled(state == "IDLE")
        self._preset_combo.setEnabled(state == "IDLE")

        if error:
            self._set_status(t("mainwindow.status.error"), theme.STATE_ERROR)
        elif recording:
            # Der Workflow steht bereits im Dropdown darueber — kein Suffix noetig.
            self._set_status(t("mainwindow.status.recording"), theme.STATE_RECORDING)
        elif state == "TRANSCRIBING":
            self._set_status(t("mainwindow.status.transcribing"), theme.STATE_PROCESSING)
        elif state == "LLM_REWRITING":
            self._set_status(t("mainwindow.status.processing"), theme.STATE_PROCESSING)
        else:
            self._set_status(t("mainwindow.status.ready"), theme.STATE_IDLE)

        if recording:
            if self._rec_start is None:
                self._rec_start = time.monotonic()
                self._update_timer_label()
                self._timer.start()
            self._timer_label.setStyleSheet(
                "font-size: 12px; font-family: monospace; font-weight: 600; "
                f"color: {theme.APP_TEXT};"
            )
        else:
            self._timer.stop()
            self._rec_start = None
            self._timer_label.setText("00:00")
            self._timer_label.setStyleSheet(
                "font-size: 12px; font-family: monospace; font-weight: 600; "
                f"color: {theme.APP_TEXT_FAINT};"
            )
        _ = busy

    def _set_status(self, text: str, color: str) -> None:
        # Statuspunkt traegt die Statusfarbe; der Text bleibt neutral —
        # ruhiger als eine voll eingefaerbte „Ampel"-Zeile.
        text_color = theme.APP_TEXT_DIM if color == theme.STATE_IDLE else theme.APP_TEXT
        self._status_label.setText(text)
        self._status_label.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {text_color};"
        )
        self._rec_indicator.setStyleSheet(f"color: {color}; font-size: 10px;")

    def set_history_count(self, count: int) -> None:
        self._btn_history.setText(t("mainwindow.button.history").format(count=count))

    def set_dictation_checked(self, checked: bool) -> None:
        self._btn_dictation.blockSignals(True)
        self._btn_dictation.setChecked(checked)
        self._btn_dictation.blockSignals(False)

    def set_preset(self, key: str) -> None:
        """Setzt den Preset-Combo auf ``key`` ohne Signal auszulösen."""
        self._preset_combo.blockSignals(True)
        for i in range(self._preset_combo.count()):
            if self._preset_combo.itemData(i) == key:
                self._preset_combo.setCurrentIndex(i)
                break
        self._preset_combo.blockSignals(False)

    def _update_timer_label(self) -> None:
        if self._rec_start is None:
            return
        elapsed = int(time.monotonic() - self._rec_start)
        self._timer_label.setText(f"{elapsed // 60:02d}:{elapsed % 60:02d}")

    def closeEvent(self, event: QCloseEvent) -> None:
        # Nicht beenden — nur verstecken; App laeuft im Tray weiter.
        event.ignore()
        self.hide()

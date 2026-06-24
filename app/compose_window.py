"""Compose window for manual text rewriting."""
from __future__ import annotations

import logging
import re
from typing import Optional

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t
from app.llm_service import LLMService
from app.config import Config, VALID_TONES
from app.paste_service import PasteService, PasteServiceError
from app.workflows import WorkflowType
from app.writing_presets import DEFAULT_PRESET_KEY, WRITING_PRESET_KEYS, preset_index

logger = logging.getLogger("blitztext.compose")

COMPOSE_WORKFLOW_ORDER: tuple[WorkflowType, ...] = (
    WorkflowType.TEXT_IMPROVER,
    WorkflowType.DAMPF_ABLASSEN,
    WorkflowType.EMOJI_TEXT,
)

# Reihenfolge des Tonfall-Selektors im Compose-Fenster. Die Werte bleiben intern
# unverändert (formal/neutral/locker); nur die Anzeige erfolgt über i18n-Labels
# (z. B. "professionell" für "formal").
COMPOSE_TONE_ORDER: tuple[str, ...] = ("locker", "neutral", "formal")

# Sentinel-Schlüssel für den zusätzlichen Compose-Eintrag „Eigene Vorlage…“.
# Bewusst kein echtes Writing-Preset, damit Hauptfenster/Tray unberührt bleiben.
COMPOSE_CUSTOM_PRESET_KEY = "__compose_custom__"

# In-memory ring buffer of successful generations for the current window
# session. Oldest variants are trimmed once the cap is exceeded.
MAX_COMPOSE_VARIANTS = 10

# Curated signature placeholders an LLM commonly emits at the end of an email,
# in German and English. We deliberately anchor on the known closing tokens
# (Name / Vorname / Nachname / Absender / Sender / Signature) rather than any
# bracketed text, so unrelated bracketed content is never replaced. An optional
# trailing comma is swallowed to avoid a dangling comma after substitution.
SIGNATURE_PLACEHOLDER_PATTERN = re.compile(
    r"\[\s*"
    r"(?:(?:dein[er]?|deine|ihr[er]?|ihre|mein[er]?|meine|your|my)\s+)?"
    r"(?:vorname|nachname|full\s+name|name|absender|sender|signature|unterschrift)"
    r"(?:\s+nachname)?"
    r"\s*\]\s*,?",
    re.IGNORECASE,
)


def _scrub_secret(text: str, secret: str) -> str:
    if secret and text:
        return text.replace(secret, "***")
    return text


class PromptEditorDialog(QDialog):
    """Shows the resolved system prompt + user message and allows editing before sending."""

    def __init__(
        self,
        system_prompt: str,
        user_message: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("compose.prompt_preview.title"))
        self.setModal(True)
        self.resize(640, 500)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        layout.addWidget(QLabel(t("compose.prompt_preview.system_label")))
        self._system_edit = QPlainTextEdit(system_prompt)
        self._system_edit.setMinimumHeight(160)
        layout.addWidget(self._system_edit, 2)

        layout.addWidget(QLabel(t("compose.prompt_preview.user_label")))
        self._user_edit = QPlainTextEdit(user_message)
        self._user_edit.setMinimumHeight(80)
        layout.addWidget(self._user_edit, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_send = QPushButton(t("compose.prompt_preview.send_btn"))
        btn_send.setDefault(True)
        btn_send.clicked.connect(self.accept)
        btn_row.addWidget(btn_send)
        btn_cancel = QPushButton(t("compose.prompt_preview.cancel_btn"))
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def get_system_prompt(self) -> str:
        return self._system_edit.toPlainText()

    def get_user_message(self) -> str:
        return self._user_edit.toPlainText()


class _ComposeWorker(QObject):
    """Background worker for manual text rewriting."""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(
        self,
        service: LLMService,
        workflow: WorkflowType,
        text: str,
        writing_preset: str,
        tone: Optional[str] = None,
        custom_prompt: Optional[str] = None,
        raw_system_prompt: Optional[str] = None,
        raw_user_message: Optional[str] = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._workflow = workflow
        self._text = text
        self._writing_preset = writing_preset
        self._tone = tone
        self._custom_prompt = custom_prompt
        self._raw_system_prompt = raw_system_prompt
        self._raw_user_message = raw_user_message
        self._cancelled = False

    def request_cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        try:
            if self._cancelled or QThread.currentThread().isInterruptionRequested():
                return
            if self._raw_system_prompt is not None:
                user_msg = self._raw_user_message if self._raw_user_message is not None else self._text
                result = self._service.rewrite_raw(self._raw_system_prompt, user_msg)
            else:
                result = self._service.rewrite_text(
                    self._workflow,
                    self._text,
                    writing_preset=self._writing_preset,
                    tone=self._tone,
                    custom_prompt=self._custom_prompt,
                )
            if self._cancelled or QThread.currentThread().isInterruptionRequested():
                return
            self.finished.emit(result)
        except Exception as exc:
            if self._cancelled:
                return
            secret = getattr(self._service, "api_key", "")
            self.error.emit(_scrub_secret(str(exc), secret))


class ComposeWindow(QDialog):
    """Modeless dialog for composing text through existing LLM workflows."""

    def __init__(
        self,
        llm_service: LLMService,
        paste_service: PasteService,
        config: Config,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._llm_service = llm_service
        self._paste_service = paste_service
        self._config = config
        self._worker_thread: Optional[QThread] = None
        self._worker: Optional[_ComposeWorker] = None
        self._detached_threads: list[QThread] = []
        self._busy = False
        self._shortcuts: list[QShortcut] = []
        # In-memory variant history (one entry per successful generation).
        self._variants: list[str] = []
        self._variant_index: int = -1

        self.setWindowTitle(t("compose.window_title"))
        self.setMinimumSize(600, 500)
        self.resize(760, 600)

        self._setup_ui()
        self.retranslate_ui()
        self._sync_state()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(8)

        self.lblWorkflow = QLabel()
        header_row.addWidget(self.lblWorkflow)

        self.cmbWorkflow = QComboBox()
        self.cmbWorkflow.setMinimumWidth(160)
        header_row.addWidget(self.cmbWorkflow, 1)

        self.lblPreset = QLabel()
        header_row.addWidget(self.lblPreset)

        self.cmbPreset = QComboBox()
        self.cmbPreset.setMinimumWidth(180)
        header_row.addWidget(self.cmbPreset, 1)

        self.lblTone = QLabel()
        header_row.addWidget(self.lblTone)

        self.cmbTone = QComboBox()
        self.cmbTone.setMinimumWidth(130)
        header_row.addWidget(self.cmbTone, 1)

        self.chkVoiceRouting = QCheckBox()
        self.chkVoiceRouting.setEnabled(False)
        self.chkVoiceRouting.setToolTip(t("compose.voice_routing.help"))
        # Future hook only; phase I-1 must not alter the existing transcription path.
        header_row.addWidget(self.chkVoiceRouting)

        header_row.addStretch(1)
        layout.addLayout(header_row)

        self.splitMain = QSplitter(Qt.Orientation.Vertical)
        self.splitMain.setChildrenCollapsible(False)

        input_panel = QWidget()
        input_layout = QVBoxLayout(input_panel)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(6)

        self.lblInput = QLabel()
        input_layout.addWidget(self.lblInput)

        self.txtInput = QPlainTextEdit()
        self.txtInput.textChanged.connect(self._sync_state)
        input_layout.addWidget(self.txtInput, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.btnAction = QPushButton()
        self.btnAction.setMinimumWidth(140)
        self.btnAction.clicked.connect(self._on_improve_clicked)
        action_row.addWidget(self.btnAction)

        self.btnShowPrompt = QPushButton()
        self.btnShowPrompt.clicked.connect(self._on_show_prompt_clicked)
        action_row.addWidget(self.btnShowPrompt)

        self.lblStatus = QLabel()
        self.lblStatus.setVisible(False)
        self.lblStatus.setWordWrap(True)
        action_row.addWidget(self.lblStatus, 1)
        input_layout.addLayout(action_row)

        output_panel = QWidget()
        output_layout = QVBoxLayout(output_panel)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(6)

        output_header = QHBoxLayout()
        output_header.setSpacing(8)

        self.lblOutput = QLabel()
        output_header.addWidget(self.lblOutput)

        output_header.addStretch(1)

        self.btnPrev = QPushButton("◀")
        self.btnPrev.setMaximumWidth(40)
        self.btnPrev.clicked.connect(self._on_prev_variant)
        output_header.addWidget(self.btnPrev)

        self.lblVariantCounter = QLabel()
        output_header.addWidget(self.lblVariantCounter)

        self.btnNext = QPushButton("▶")
        self.btnNext.setMaximumWidth(40)
        self.btnNext.clicked.connect(self._on_next_variant)
        output_header.addWidget(self.btnNext)

        output_layout.addLayout(output_header)

        self.txtOutput = QPlainTextEdit()
        self.txtOutput.textChanged.connect(self._on_output_text_changed)
        output_layout.addWidget(self.txtOutput, 1)

        footer_row = QHBoxLayout()
        footer_row.setSpacing(8)
        footer_row.addStretch(1)

        self.btnCopy = QPushButton()
        self.btnCopy.clicked.connect(self._on_copy_clicked)
        footer_row.addWidget(self.btnCopy)

        self.btnPaste = QPushButton()
        self.btnPaste.clicked.connect(self._on_paste_clicked)
        footer_row.addWidget(self.btnPaste)

        self.btnSignature = QPushButton()
        self.btnSignature.clicked.connect(self._on_append_signature_clicked)
        footer_row.addWidget(self.btnSignature)

        self.btnClose = QPushButton()
        self.btnClose.clicked.connect(self.close)
        footer_row.addWidget(self.btnClose)

        output_layout.addLayout(footer_row)

        self.splitMain.addWidget(input_panel)
        self.splitMain.addWidget(output_panel)
        self.splitMain.setStretchFactor(0, 3)
        self.splitMain.setStretchFactor(1, 2)
        self.splitMain.setSizes([330, 240])
        layout.addWidget(self.splitMain, 1)

        self._install_shortcuts()
        self._populate_workflow_combo()
        self._populate_preset_combo()
        self._populate_tone_combo()
        self.cmbWorkflow.currentIndexChanged.connect(self._on_selectors_changed)
        self.cmbPreset.currentIndexChanged.connect(self._on_selectors_changed)
        self._update_tone_state()

    def _install_shortcuts(self) -> None:
        self._add_shortcut(self.txtInput, "Ctrl+Return", self._on_improve_clicked)
        self._add_shortcut(self.txtInput, "Ctrl+Enter", self._on_improve_clicked)
        self._add_shortcut(self.txtOutput, "Ctrl+Return", self._on_paste_clicked)
        self._add_shortcut(self.txtOutput, "Ctrl+Enter", self._on_paste_clicked)
        self._add_shortcut(self.txtOutput, "Ctrl+Shift+V", self._on_paste_clicked)

    def _add_shortcut(self, parent: QWidget, sequence: str, callback) -> None:
        shortcut = QShortcut(QKeySequence(sequence), parent)
        shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        shortcut.activated.connect(callback)
        self._shortcuts.append(shortcut)

    def _populate_workflow_combo(self, selected: Optional[WorkflowType] = None) -> None:
        if selected is None and hasattr(self, "cmbWorkflow"):
            selected = self._selected_workflow()
        self.cmbWorkflow.blockSignals(True)
        self.cmbWorkflow.clear()
        for workflow in COMPOSE_WORKFLOW_ORDER:
            self.cmbWorkflow.addItem(t(f"workflow.{workflow.value}.name"), workflow)
        target = selected or COMPOSE_WORKFLOW_ORDER[0]
        index = self.cmbWorkflow.findData(target)
        self.cmbWorkflow.setCurrentIndex(index if index >= 0 else 0)
        self.cmbWorkflow.blockSignals(False)

    def _populate_preset_combo(self, selected: Optional[str] = None) -> None:
        if selected is None and hasattr(self, "cmbPreset"):
            selected = self._selected_preset()
        self.cmbPreset.blockSignals(True)
        self.cmbPreset.clear()
        for key in WRITING_PRESET_KEYS:
            self.cmbPreset.addItem(t(f"preset.{key}.name"), key)
        # Zusätzlicher, nur im Compose-Fenster sichtbarer Freitext-Eintrag.
        self.cmbPreset.addItem(t("compose.preset.custom"), COMPOSE_CUSTOM_PRESET_KEY)
        target = selected or preset_index(self._llm_service.writing_preset)
        if isinstance(target, str):
            index = self.cmbPreset.findData(target)
        else:
            index = int(target)
        self.cmbPreset.setCurrentIndex(index if index >= 0 else preset_index(self._llm_service.writing_preset))
        self.cmbPreset.blockSignals(False)

    def _selected_workflow(self) -> WorkflowType:
        workflow = self.cmbWorkflow.currentData()
        return workflow if isinstance(workflow, WorkflowType) else COMPOSE_WORKFLOW_ORDER[0]

    def _selected_preset(self) -> str:
        preset = self.cmbPreset.currentData()
        if isinstance(preset, str) and preset:
            return preset
        return self._llm_service.writing_preset

    def _populate_tone_combo(self, selected: Optional[str] = None) -> None:
        if selected is None and hasattr(self, "cmbTone"):
            selected = self._selected_tone()
        self.cmbTone.blockSignals(True)
        self.cmbTone.clear()
        for value in COMPOSE_TONE_ORDER:
            self.cmbTone.addItem(t(f"tone.{value}"), value)
        target = selected or self._config.text_improver_tone
        index = self.cmbTone.findData(target)
        if index < 0:
            index = self.cmbTone.findData("neutral")
        self.cmbTone.setCurrentIndex(index if index >= 0 else 0)
        self.cmbTone.blockSignals(False)

    def _selected_tone(self) -> str:
        tone = self.cmbTone.currentData()
        if isinstance(tone, str) and tone in VALID_TONES:
            return tone
        return self._config.text_improver_tone

    def _is_custom_preset(self) -> bool:
        return self._selected_preset() == COMPOSE_CUSTOM_PRESET_KEY

    @pyqtSlot()
    def _on_selectors_changed(self) -> None:
        self._update_tone_state()

    def _update_tone_state(self) -> None:
        """Sichtbarkeit/Aktivierung des Tonfall-Selektors je nach Workflow+Vorlage.

        Tonfall ist nur sinnvoll im Text-Verbesserer (Blitztext+) mit der Vorlage
        „Standard“. Bei anderen Vorlagen bestimmt die Vorlage den Stil selbst, der
        Selektor bleibt sichtbar, aber ausgegraut. Bei Dampf/Emoji entfällt er.
        """
        workflow = self._selected_workflow()
        is_text_improver = workflow == WorkflowType.TEXT_IMPROVER
        self.lblTone.setVisible(is_text_improver)
        self.cmbTone.setVisible(is_text_improver)
        if not is_text_improver:
            return
        is_standard = self._selected_preset() == DEFAULT_PRESET_KEY
        self.cmbTone.setEnabled(is_standard)
        self.cmbTone.setToolTip(
            t("compose.tone.tooltip_active")
            if is_standard
            else t("compose.tone.tooltip_preset_overrides")
        )

    def _has_input(self) -> bool:
        return bool(self.txtInput.toPlainText().strip())

    def _has_output(self) -> bool:
        return bool(self.txtOutput.toPlainText().strip())

    def _show_status(self, text: str, *, error: bool = False) -> None:
        self.lblStatus.setText(text)
        self.lblStatus.setVisible(bool(text))
        if error:
            self.lblStatus.setStyleSheet("color: #f44336;")
        else:
            self.lblStatus.setStyleSheet("")

    def _hide_status(self) -> None:
        self.lblStatus.clear()
        self.lblStatus.setVisible(False)
        self.lblStatus.setStyleSheet("")

    def _set_busy(self, busy: bool, *, keep_status: bool = False) -> None:
        self._busy = busy
        self.txtInput.setReadOnly(busy)
        if busy:
            self.btnAction.setEnabled(False)
            self.btnShowPrompt.setEnabled(False)
            self.btnCopy.setEnabled(False)
            self.btnPaste.setEnabled(False)
            self._show_status(t("compose.status.processing"))
        else:
            if not keep_status:
                self._hide_status()
        self._sync_state()

    def _sync_state(self) -> None:
        self._update_variant_nav()
        if self._busy:
            self.btnAction.setEnabled(False)
            self.btnCopy.setEnabled(False)
            self.btnPaste.setEnabled(False)
            return
        self.btnAction.setEnabled(self._has_input())
        self.btnShowPrompt.setEnabled(self._has_input())
        has_output = self._has_output()
        self.btnCopy.setEnabled(has_output)
        self.btnPaste.setEnabled(has_output)

        raw_sig = self._config.compose_signature_text
        if has_output and raw_sig.strip():
            sig = raw_sig.rstrip()
            text = self.txtOutput.toPlainText()
            # Enable only while appending would actually change something:
            # a placeholder is still present, or the signature isn't there yet.
            has_placeholder = SIGNATURE_PLACEHOLDER_PATTERN.search(text) is not None
            self.btnSignature.setEnabled(has_placeholder or not text.endswith(sig))
            self.btnSignature.setVisible(True)
        else:
            self.btnSignature.setEnabled(False)
            self.btnSignature.setVisible(bool(raw_sig.strip()))

    def _update_variant_nav(self) -> None:
        total = len(self._variants)
        has_variants = total > 0
        self.btnPrev.setVisible(has_variants)
        self.btnNext.setVisible(has_variants)
        self.lblVariantCounter.setVisible(has_variants)
        if not has_variants:
            self.lblVariantCounter.setText(t("compose.variant.none"))
            self.btnPrev.setEnabled(False)
            self.btnNext.setEnabled(False)
            return
        self.lblVariantCounter.setText(
            t("compose.variant.counter").format(
                current=self._variant_index + 1, total=total
            )
        )
        at_border_start = self._variant_index <= 0
        at_border_end = self._variant_index >= total - 1
        self.btnPrev.setEnabled(not self._busy and not at_border_start)
        self.btnNext.setEnabled(not self._busy and not at_border_end)

    def _set_output_guarded(self, text: str) -> None:
        """Set the output field without registering it as a manual edit."""
        self.txtOutput.blockSignals(True)
        try:
            self.txtOutput.setPlainText(text)
        finally:
            self.txtOutput.blockSignals(False)

    def _append_variant(self, text: str) -> None:
        self._variants.append(text)
        if len(self._variants) > MAX_COMPOSE_VARIANTS:
            self._variants.pop(0)
        self._variant_index = len(self._variants) - 1
        self._set_output_guarded(text)

    def _show_current_variant(self) -> None:
        self._set_output_guarded(self._variants[self._variant_index])
        self._sync_state()

    @pyqtSlot()
    def _on_prev_variant(self) -> None:
        if self._busy or self._variant_index <= 0:
            return
        self._variant_index -= 1
        self._show_current_variant()

    @pyqtSlot()
    def _on_next_variant(self) -> None:
        if self._busy or self._variant_index >= len(self._variants) - 1:
            return
        self._variant_index += 1
        self._show_current_variant()

    @pyqtSlot()
    def _on_output_text_changed(self) -> None:
        # A genuine manual edit updates the active variant in place; guarded
        # programmatic updates (navigation/generation) never reach this slot.
        if 0 <= self._variant_index < len(self._variants):
            self._variants[self._variant_index] = self.txtOutput.toPlainText()
        self._sync_state()

    def _append_signature(self) -> None:
        raw_sig = self._config.compose_signature_text
        if not raw_sig.strip():
            return

        # Strip trailing whitespace/newlines/tabs the user may have saved by
        # accident, so substitution never leaves dangling blank lines.
        sig = raw_sig.rstrip()
        original = self.txtOutput.toPlainText()

        # If the LLM left a closing placeholder like [Ihr Name] or [Your Name],
        # replace it in place (incl. an optional trailing comma) instead of
        # appending a second signature below it.
        text, replaced = SIGNATURE_PLACEHOLDER_PATTERN.subn(sig, original)
        if not replaced:
            # No placeholder: append classically at the bottom.
            if text.endswith(sig):
                return
            if text and not text.endswith("\n\n"):
                text += "\n" if text.endswith("\n") else "\n\n"
            text += sig

        if text == original:
            return

        self._set_output_guarded(text)
        if 0 <= self._variant_index < len(self._variants):
            self._variants[self._variant_index] = text
        self._sync_state()

    @pyqtSlot()
    def _on_append_signature_clicked(self) -> None:
        self._append_signature()

    def set_input_text(self, text: str) -> None:
        self.txtInput.setPlainText(text)
        self._variants = []
        self._variant_index = -1
        self._set_output_guarded("")
        self._hide_status()
        self._sync_state()

    def retranslate_ui(self) -> None:
        """Refresh visible text to the active UI language."""
        current_workflow = self._selected_workflow()
        current_preset = self._selected_preset()
        current_tone = self._selected_tone()

        self.setWindowTitle(t("compose.window_title"))
        self.lblWorkflow.setText(t("compose.workflow.label"))
        self.lblPreset.setText(t("compose.preset.label"))
        self.lblTone.setText(t("compose.tone.label"))
        self.chkVoiceRouting.setText(t("compose.voice_routing.label"))
        self.chkVoiceRouting.setToolTip(t("compose.voice_routing.help"))
        self.lblInput.setText(t("compose.input.label"))
        self.lblOutput.setText(t("compose.output.label"))
        self.btnAction.setText(t("compose.button.improve"))
        self.btnShowPrompt.setText(t("compose.btn.show_prompt"))
        self.btnShowPrompt.setToolTip(t("compose.prompt_preview.tooltip"))
        self.btnCopy.setText(t("compose.button.copy"))
        self.btnPaste.setText(t("compose.button.insert_close"))
        self.btnClose.setText(t("compose.button.close"))
        self.btnSignature.setText(t("compose.btn_append_signature"))
        self.btnSignature.setToolTip(t("compose.tooltip_append_signature"))
        self.btnPrev.setToolTip(t("compose.variant.prev"))
        self.btnNext.setToolTip(t("compose.variant.next"))

        self._populate_workflow_combo(current_workflow)
        self._populate_preset_combo(current_preset)
        self._populate_tone_combo(current_tone)
        self._update_tone_state()

        if self._busy:
            self._show_status(t("compose.status.processing"))
        elif not self.lblStatus.text():
            self._hide_status()

        self._sync_state()

    def _start_worker(self, text: str) -> None:
        workflow = self._selected_workflow()
        tone = self._selected_tone()
        custom_prompt: Optional[str] = None
        if self._is_custom_preset():
            # Freitext-Vorlage: Basis bleibt „Standard“, der freie System-Prompt
            # wird separat durchgereicht (greift nur im Text-Verbesserer).
            writing_preset = DEFAULT_PRESET_KEY
            custom_prompt = self._config.compose_custom_preset_text
        else:
            writing_preset = self._selected_preset()

        thread = QThread(self)
        worker = _ComposeWorker(
            self._llm_service,
            workflow,
            text,
            writing_preset,
            tone=tone,
            custom_prompt=custom_prompt,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_worker_result)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_worker_thread_finished)
        self._worker_thread = thread
        self._worker = worker
        self._set_busy(True)
        thread.start()

    def _cleanup_worker_state(self) -> None:
        self._worker = None
        self._worker_thread = None

    def _detach_worker_thread(self) -> None:
        worker = self._worker
        thread = self._worker_thread
        if worker is not None:
            worker.request_cancel()
        if thread is not None:
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(1500):
                try:
                    thread.setParent(None)
                except Exception:
                    pass
                thread._detached_worker = worker  # type: ignore[attr-defined]
                self._detached_threads.append(thread)
                thread.finished.connect(lambda t=thread: self._on_detached_thread_finished(t))
        self._cleanup_worker_state()

    def _on_detached_thread_finished(self, thread: QThread) -> None:
        self._detached_threads = [t for t in self._detached_threads if t is not thread]
        thread.deleteLater()

    @pyqtSlot()
    def _on_improve_clicked(self) -> None:
        if self._busy:
            return
        text = self.txtInput.toPlainText()
        if not text.strip():
            self._show_status(t("compose.status.empty_input"), error=True)
            return
        self._start_worker(text)

    @pyqtSlot()
    def _on_show_prompt_clicked(self) -> None:
        if self._busy:
            return
        text = self.txtInput.toPlainText()
        if not text.strip():
            self._show_status(t("compose.status.empty_input"), error=True)
            return

        workflow = self._selected_workflow()
        tone = self._selected_tone()
        custom_prompt: Optional[str] = None
        writing_preset = self._selected_preset()
        if self._is_custom_preset():
            writing_preset = DEFAULT_PRESET_KEY
            custom_prompt = self._config.compose_custom_preset_text

        system_prompt = self._llm_service.build_system_prompt(
            workflow, writing_preset=writing_preset, tone=tone, custom_prompt=custom_prompt
        )
        dialog = PromptEditorDialog(system_prompt, text.strip(), parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._start_worker_raw(dialog.get_system_prompt(), dialog.get_user_message())

    def _start_worker_raw(self, system_prompt: str, user_message: str) -> None:
        thread = QThread(self)
        worker = _ComposeWorker(
            self._llm_service,
            self._selected_workflow(),
            user_message,
            self._selected_preset(),
            raw_system_prompt=system_prompt,
            raw_user_message=user_message,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_worker_result)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_worker_thread_finished)
        self._worker_thread = thread
        self._worker = worker
        self._set_busy(True)
        thread.start()

    @pyqtSlot(str)
    def _on_worker_result(self, result_text: str) -> None:
        logger.info("Compose rewrite success (%d chars)", len(result_text))
        self._append_variant(result_text)
        if self._config.compose_signature_auto_append:
            self._append_signature()
        self._set_busy(False)

    @pyqtSlot(str)
    def _on_worker_error(self, message: str) -> None:
        logger.error("Compose rewrite error: %s", message)
        self._show_status(message, error=True)
        self._set_busy(False, keep_status=True)

    @pyqtSlot()
    def _on_worker_thread_finished(self) -> None:
        if self._worker_thread is not None:
            self._worker_thread = None
        if self._worker is not None:
            self._worker = None

    @pyqtSlot()
    def _on_copy_clicked(self) -> None:
        text = self.txtOutput.toPlainText()
        if not text.strip():
            return
        try:
            QApplication.clipboard().setText(text)
        except Exception as exc:  # pragma: no cover - defensive
            self._show_status(t("compose.status.error").format(message=str(exc)), error=True)

    @pyqtSlot()
    def _on_paste_clicked(self) -> None:
        text = self.txtOutput.toPlainText()
        if not text.strip():
            return
        try:
            self._paste_service.paste(text, force_autopaste=True)
        except PasteServiceError as exc:
            self._show_status(t("compose.status.error").format(message=str(exc)), error=True)
            return
        except Exception as exc:  # pragma: no cover - defensive
            self._show_status(t("compose.status.error").format(message=str(exc)), error=True)
            return
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._busy or (self._worker_thread is not None and self._worker_thread.isRunning()):
            self._detach_worker_thread()
        super().closeEvent(event)

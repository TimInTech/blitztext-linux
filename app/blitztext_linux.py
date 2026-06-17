#!/usr/bin/env python3
"""BlitztextLinux main application.

Combines system tray operations, settings UI, and hotkey actions using evdev,
Parec, Whisper, and OpenAI.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, Qt, QThread, QThreadPool, QRunnable, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QAction, QBrush, QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QFormLayout, QComboBox, QLineEdit, QCheckBox, QPlainTextEdit,
    QPushButton, QDialogButtonBox, QLabel, QMessageBox, QMenu, QSystemTrayIcon, QStyle,
    QListWidget,
)

# Make project importable when running directly
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from app.config import Config, VALID_HOTKEY_KEYS
from app.llm_service import LLMService, WorkflowType, LLM_WORKFLOWS, LLMServiceError
from app.writing_presets import WRITING_PRESETS, WRITING_PRESET_KEYS, preset_index
from app.hotkey_service import HotkeyWorker
from app.audio_recorder import AudioRecorder, AudioRecorderError
from app.transcribe import transcribe, TranscribeError
from app.paste_service import PasteService, PasteServiceError
from app.history_panel import HistoryPanel
from app.tts_window import TtsWindow
from app.main_window import MainWindow
from app import notify as notify_service
from app import __version__ as APP_VERSION

# Set up module logger
logger = logging.getLogger("blitztext.main")


def _configure_qt_platform() -> None:
    """Prefer native Wayland when a Wayland session is available."""
    if os.environ.get("QT_QPA_PLATFORM"):
        return
    if _wayland_display_available(os.environ.get("WAYLAND_DISPLAY")):
        os.environ["QT_QPA_PLATFORM"] = "wayland"


def _wayland_display_available(display_name: Optional[str]) -> bool:
    """Return True when WAYLAND_DISPLAY points to an existing socket path."""
    if not display_name:
        return False

    if os.path.isabs(display_name):
        return os.path.exists(display_name)

    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_dir:
        return False

    return os.path.exists(os.path.join(runtime_dir, display_name))


def _infer_wayland_display() -> Optional[str]:
    """Infer a Wayland socket name from XDG_RUNTIME_DIR when env import lagged."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_dir or not os.path.isdir(runtime_dir):
        return None

    candidates = []
    try:
        for name in os.listdir(runtime_dir):
            if name.startswith("wayland-") and os.path.exists(os.path.join(runtime_dir, name)):
                candidates.append(name)
    except OSError:
        return None

    return sorted(candidates)[0] if candidates else None


def _is_hotkey_device_access_error(err_msg: str) -> bool:
    """Return True for hotkey startup errors that can fall back to GUI/tray."""
    text = err_msg.casefold()
    return any(marker in text for marker in ("tastatur", "input", "evdev"))


def _require_display_environment() -> None:
    """Exit before QApplication when no GUI session variables are present."""
    if _wayland_display_available(os.environ.get("WAYLAND_DISPLAY")):
        return

    if os.environ.get("DISPLAY"):
        if os.environ.get("WAYLAND_DISPLAY"):
            print(
                "Warning: WAYLAND_DISPLAY is not usable; falling back to DISPLAY.",
                file=sys.stderr,
                flush=True,
            )
            os.environ.pop("WAYLAND_DISPLAY", None)
        return

    inferred_wayland = _infer_wayland_display()
    if inferred_wayland:
        os.environ["WAYLAND_DISPLAY"] = inferred_wayland
        return

    print("ERROR: No usable display environment set. Exiting.", file=sys.stderr, flush=True)
    sys.exit(1)


def create_help_label(text: str) -> QLabel:
    """Create a styled small help label for config fields."""
    label = QLabel(text)
    label.setStyleSheet("color: gray; font-size: 10px;")
    label.setWordWrap(True)
    return label


class SettingsDialog(QDialog):
    """Settings dialog for configuring BlitztextLinux."""

    def __init__(self, config: Config, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Blitztext Einstellungen")
        self.resize(550, 480)
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(15)

        # Tabs
        self.tabs = QTabWidget()

        # Tab 1: Whisper & Audio
        tab_whisper = QWidget()
        form_whisper = QFormLayout(tab_whisper)
        form_whisper.setSpacing(10)

        self.combo_model = QComboBox()
        self.combo_model.addItems(["tiny", "base", "small", "medium", "large", "large-v2", "large-v3", "large-v3-turbo"])
        self.combo_model.setCurrentText(self.config.model)

        self.combo_backend = QComboBox()
        self.combo_backend.addItems(["openai-whisper", "faster-whisper"])
        self.combo_backend.setCurrentText(self.config.backend)

        self.edit_language = QLineEdit()
        self.edit_language.setText(self.config.language)
        self.edit_language.setPlaceholderText("de, en, auto...")

        self.edit_audio_device = QLineEdit()
        self.edit_audio_device.setText(self.config.audio_device)
        self.edit_audio_device.setPlaceholderText("@DEFAULT_SOURCE@")

        self.combo_hotkey_mode = QComboBox()
        self.combo_hotkey_mode.addItems(["toggle", "hold"])
        self.combo_hotkey_mode.setCurrentText(self.config.hotkey_mode)

        self.combo_transcription_key = QComboBox()
        self.combo_transcription_key.addItems(sorted(VALID_HOTKEY_KEYS))
        self.combo_transcription_key.setCurrentText(self.config.transcription_hotkey)

        form_whisper.addRow("Whisper-Modell:", self.combo_model)
        form_whisper.addRow("", create_help_label("Wählen Sie die Modellgröße. Größere Modelle sind genauer, benötigen aber mehr Ressourcen."))

        form_whisper.addRow("Transkription-Backend:", self.combo_backend)
        form_whisper.addRow("", create_help_label("faster-whisper ist deutlich schneller und ressourcenschonender."))

        form_whisper.addRow("Sprache:", self.edit_language)
        form_whisper.addRow("", create_help_label("Zweistelliger Ländercode (z. B. 'de', 'en') oder 'auto' für automatische Erkennung."))

        form_whisper.addRow("Audio-Eingabegerät:", self.edit_audio_device)
        form_whisper.addRow("", create_help_label("'@DEFAULT_SOURCE@' nutzt das Standardmikrofon von PulseAudio/PipeWire."))

        form_whisper.addRow("Hotkey-Modus:", self.combo_hotkey_mode)
        form_whisper.addRow("", create_help_label("toggle: Einmal drücken zum Starten, erneut drücken zum Stoppen.\nhold: Gedrückt halten zum Aufnehmen, Loslassen zum Stoppen."))

        form_whisper.addRow("Aufnahme-Taste:", self.combo_transcription_key)
        form_whisper.addRow("", create_help_label("Einzelne Taste ohne Modifier (z. B. KEY_LEFTALT). Änderung wird sofort übernommen."))

        self.tabs.addTab(tab_whisper, "Spracherkennung")

        # Tab 2: LLM (KI)
        tab_llm = QWidget()
        form_llm = QFormLayout(tab_llm)
        form_llm.setSpacing(10)

        self.edit_api_key_env = QLineEdit()
        self.edit_api_key_env.setText(self.config.openai_api_key_env)
        self.edit_api_key_env.setPlaceholderText("OPENAI_API_KEY")
        self.edit_api_key_env.textChanged.connect(lambda *_: self._refresh_api_key_status())

        self.lbl_api_key_status = QLabel()
        self.lbl_api_key_status.setWordWrap(True)

        api_key_layout = QVBoxLayout()
        api_key_layout.addWidget(self.edit_api_key_env)
        api_key_layout.addWidget(self.lbl_api_key_status)
        if self.config.has_legacy_openai_api_key:
            self.lbl_legacy_api_key_notice = QLabel(
                "Legacy openai_api_key gefunden. Er wird beim nächsten Speichern entfernt."
            )
            self.lbl_legacy_api_key_notice.setWordWrap(True)
            self.lbl_legacy_api_key_notice.setStyleSheet("color: #b26a00; font-size: 10px;")
            api_key_layout.addWidget(self.lbl_legacy_api_key_notice)
        else:
            self.lbl_legacy_api_key_notice = None

        self._refresh_api_key_status()

        self.combo_llm_provider = QComboBox()
        self.combo_llm_provider.addItem("OpenAI", "openai")
        self.combo_llm_provider.addItem("OpenRouter", "openrouter")
        self.combo_llm_provider.addItem("Eigener Endpunkt", "custom")
        provider_index = self.combo_llm_provider.findData(self.config.llm_provider)
        self.combo_llm_provider.setCurrentIndex(provider_index if provider_index >= 0 else 0)
        self.combo_llm_provider.currentIndexChanged.connect(lambda *_: self._on_llm_provider_changed())

        self.edit_base_url = QLineEdit()
        self.edit_base_url.setText(self.config.llm_base_url)
        self.edit_base_url.setPlaceholderText("https://openrouter.ai/api/v1")
        self.edit_base_url.setEnabled(self.config.llm_provider != "openai")

        self.edit_llm_model = QLineEdit()
        self.edit_llm_model.setText(self.config.llm_model)
        self.edit_llm_model.setPlaceholderText("gpt-4o-mini")

        self.combo_tone = QComboBox()
        self.combo_tone.addItems(["formal", "neutral", "locker"])
        self.combo_tone.setCurrentText(self.config.text_improver_tone)

        self.combo_writing_preset = QComboBox()
        for key in WRITING_PRESET_KEYS:
            self.combo_writing_preset.addItem(WRITING_PRESETS[key].display_name, key)
        self.combo_writing_preset.setCurrentIndex(preset_index(self.config.writing_preset))

        self.combo_emoji = QComboBox()
        self.combo_emoji.addItems(["wenig", "mittel", "viel"])
        self.combo_emoji.setCurrentText(self.config.emoji_density)

        self.edit_dampf_prompt = QPlainTextEdit()
        self.edit_dampf_prompt.setPlainText(self.config.dampf_system_prompt)
        self.edit_dampf_prompt.setPlaceholderText("Standard-Systemprompt verwenden...")

        self.edit_custom_term = QLineEdit()
        self.edit_custom_term.setPlaceholderText("z. B. Blitztext")
        self.edit_custom_term.returnPressed.connect(self._add_custom_term)
        self.list_custom_terms = QListWidget()
        self.list_custom_terms.addItems(self.config.custom_terms)
        self.list_custom_terms.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.btn_add_custom_term = QPushButton("Hinzufügen")
        self.btn_add_custom_term.clicked.connect(self._add_custom_term)
        self.btn_remove_custom_term = QPushButton("Ausgewählte entfernen")
        self.btn_remove_custom_term.clicked.connect(self._remove_selected_custom_term)

        custom_terms_input_layout = QHBoxLayout()
        custom_terms_input_layout.addWidget(self.edit_custom_term)
        custom_terms_input_layout.addWidget(self.btn_add_custom_term)

        custom_terms_layout = QVBoxLayout()
        custom_terms_layout.addLayout(custom_terms_input_layout)
        custom_terms_layout.addWidget(self.list_custom_terms)
        custom_terms_layout.addWidget(self.btn_remove_custom_term)

        custom_terms_widget = QWidget()
        custom_terms_widget.setLayout(custom_terms_layout)

        form_llm.addRow("API-Key-Umgebung:", api_key_layout)
        form_llm.addRow("", create_help_label("Nur der Name der Umgebungsvariable wird gespeichert. Der Schlüssel selbst wird aus os.environ gelesen (secrets.env). Für OpenRouter z. B. OPENROUTER_API_KEY."))

        form_llm.addRow("LLM-Anbieter:", self.combo_llm_provider)
        form_llm.addRow("", create_help_label("OpenAI = Standard. OpenRouter und 'Eigener Endpunkt' nutzen das OpenAI-kompatible API über eine eigene Basis-URL und ein eigenes Modell."))
        form_llm.addRow("Basis-URL (base_url):", self.edit_base_url)
        form_llm.addRow("", create_help_label("Leer = OpenAI-Standard. Für OpenRouter: https://openrouter.ai/api/v1. Muss mit http:// oder https:// beginnen."))
        form_llm.addRow("LLM-Modell:", self.edit_llm_model)
        form_llm.addRow("", create_help_label("Modellname beim Anbieter, z. B. 'gpt-4o-mini' (OpenAI) oder 'openai/gpt-4o' (OpenRouter)."))

        form_llm.addRow("Text-Verbesserer Tonfall:", self.combo_tone)
        form_llm.addRow("Schreibstil-Vorlage:", self.combo_writing_preset)
        form_llm.addRow("", create_help_label("Vorlage für den Text-Verbesserer (z. B. E-Mail formell, Stichpunkte). Bei 'Standard' greift der Tonfall oben; jede andere Vorlage bestimmt den Schreibstil selbst und ersetzt den Tonfall."))
        form_llm.addRow("Emoji-Dichte:", self.combo_emoji)

        form_llm.addRow("Dampf-Umschreiber Prompt:", self.edit_dampf_prompt)
        form_llm.addRow("", create_help_label("Eigener System-Prompt, um wütende Aussagen in eine professionelle Form umzuschreiben."))
        form_llm.addRow("Eigennamen / Begriffe:", custom_terms_widget)
        form_llm.addRow("", create_help_label("Wörter, Namen und Fachbegriffe, die bei Transkription und KI-Umschreibung exakt beibehalten werden sollen."))

        self.tabs.addTab(tab_llm, "KI-Workflows")

        # Tab 3: Allgemein
        tab_general = QWidget()
        form_general = QFormLayout(tab_general)
        form_general.setSpacing(10)

        self.check_autopaste = QCheckBox("Text automatisch einfügen (Auto-Paste)")
        self.check_autopaste.setChecked(self.config.autopaste)
        form_general.addRow(self.check_autopaste)
        form_general.addRow("", create_help_label("Simuliert Strg+V nach Abschluss der Aufnahme. Benötigt das Tool 'ydotool'."))

        self.edit_notes_folder = QLineEdit()
        self.edit_notes_folder.setText(self.config.notes_folder)
        self.edit_notes_folder.setPlaceholderText(str(Path.home() / "Blitztext-Notizen"))
        form_general.addRow("Diktat-Notizordner:", self.edit_notes_folder)
        form_general.addRow("", create_help_label("Ordner für Diktat-Notizen (muss innerhalb von ~ liegen). Leer = Speichern deaktiviert."))

        self.spin_history_size = QComboBox()
        self.spin_history_size.addItems(["10", "25", "50", "75", "100"])
        self.spin_history_size.setCurrentText(str(self.config.history_size))
        form_general.addRow("Verlauf-Größe:", self.spin_history_size)
        form_general.addRow("", create_help_label("Maximale Anzahl der im Verlauf gespeicherten Einträge."))

        self.btn_open_config = QPushButton("📄  Konfigurationsdatei öffnen")
        self.btn_open_config.clicked.connect(self._open_config_file)
        form_general.addRow(self.btn_open_config)
        form_general.addRow("", create_help_label(
            "Öffnet config.json im Standard-Editor – für erweiterte Prompt- und "
            "Workflow-Anpassungen, die über die Felder oben hinausgehen."))

        # Dezente Versionsanzeige ganz unten auf der letzten Einstellungsseite
        version_label = QLabel(f"Version {APP_VERSION}")
        version_label.setStyleSheet("color: gray; font-size: 9px;")
        version_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        form_general.addRow(version_label)

        self.tabs.addTab(tab_general, "Allgemein")

        layout.addWidget(self.tabs)

        # Dialog Button Box
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.save_settings)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _refresh_api_key_status(self) -> None:
        env_name = self.edit_api_key_env.text().strip() or self.config.openai_api_key_env
        env_value = os.environ.get(env_name, "").strip()
        status = "gesetzt" if env_value else "nicht gesetzt"
        self.lbl_api_key_status.setText(f"Status: {status} ({env_name})")

    def _on_llm_provider_changed(self) -> None:
        provider = self.combo_llm_provider.currentData()
        if provider == "openrouter":
            if not self.edit_base_url.text().strip():
                self.edit_base_url.setText("https://openrouter.ai/api/v1")
            self.edit_base_url.setEnabled(True)
        elif provider == "openai":
            self.edit_base_url.setText("")
            self.edit_base_url.setEnabled(False)
        else:  # custom / eigener Endpunkt
            self.edit_base_url.setEnabled(True)

    def _open_config_file(self) -> None:
        """Open the config.json in the desktop's default editor.

        Falls die Datei noch nie gespeichert wurde oder noch ein Legacy-API-Key
        im Speicher hängt, wird sie zuvor über die bestehende, atomare
        ``config.save()``-Logik (0o600) angelegt bzw. bereinigt.
        """
        try:
            if (not self.config.config_file.is_file()) or self.config.has_legacy_openai_api_key:
                self.config.save()
            opened = QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self.config.config_file)))
            if not opened:
                QMessageBox.warning(
                    self,
                    "Öffnen fehlgeschlagen",
                    f"Konfigurationsdatei konnte nicht geöffnet werden:\n{self.config.config_file}",
                )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Fehler",
                f"Konfigurationsdatei konnte nicht geöffnet werden: {e}",
            )

    def _collect_custom_terms(self) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for index in range(self.list_custom_terms.count()):
            item = self.list_custom_terms.item(index)
            if item is None:
                continue
            term = item.text().strip()
            if not term or term in seen:
                continue
            seen.add(term)
            terms.append(term)
        return terms

    def _add_custom_term(self) -> None:
        term = self.edit_custom_term.text().strip()
        if not term:
            self.edit_custom_term.clear()
            return
        if term not in self._collect_custom_terms():
            self.list_custom_terms.addItem(term)
        self.edit_custom_term.clear()
        self.edit_custom_term.setFocus()

    def _remove_selected_custom_term(self) -> None:
        for item in self.list_custom_terms.selectedItems():
            row = self.list_custom_terms.row(item)
            self.list_custom_terms.takeItem(row)

    def save_settings(self) -> None:
        try:
            self.config.model = self.combo_model.currentText()
            self.config.backend = self.combo_backend.currentText()
            self.config.language = self.edit_language.text().strip()
            self.config.audio_device = self.edit_audio_device.text().strip()
            self.config.hotkey_mode = self.combo_hotkey_mode.currentText()
            self.config.transcription_hotkey = self.combo_transcription_key.currentText()

            self.config.openai_api_key_env = self.edit_api_key_env.text().strip()
            self.config.llm_provider = self.combo_llm_provider.currentData()
            self.config.llm_base_url = self.edit_base_url.text().strip()
            self.config.llm_model = self.edit_llm_model.text().strip()
            self.config.text_improver_tone = self.combo_tone.currentText()
            self.config.writing_preset = self.combo_writing_preset.currentData()
            self.config.emoji_density = self.combo_emoji.currentText()
            self.config.dampf_system_prompt = self.edit_dampf_prompt.toPlainText().strip()
            self.config.custom_terms = self._collect_custom_terms()

            self.config.autopaste = self.check_autopaste.isChecked()
            self.config.notes_folder = self.edit_notes_folder.text().strip()
            self.config.history_size = int(self.spin_history_size.currentText())

            self.config.save()
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Speichern", f"Konfiguration konnte nicht gespeichert werden: {e}")


class _WorkerSignals(QObject):
    """Signals for background transcription/rewrite tasks."""
    status_changed = pyqtSignal(str)  # "transcribing" | "rewriting"
    result = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal(object)


class _TranscribeWorker(QRunnable):
    """Task worker running Whisper transcription and LLM rewrite asynchronously."""

    def __init__(
        self,
        wav_file: Path,
        model: str,
        language: str,
        backend: str,
        workflow: WorkflowType,
        llm_service: LLMService,
        autopaste: bool,
        paste_service: PasteService,
        custom_terms: Optional[list[str]] = None,
    ) -> None:
        super().__init__()
        self.signals = _WorkerSignals()
        self.wav_file = wav_file
        self.model = model
        self.language = language
        self.backend = backend
        self.workflow = workflow
        self.llm_service = llm_service
        self.autopaste = autopaste
        self.paste_service = paste_service
        self.custom_terms = list(custom_terms or [])

    def _emit(self, signal_name: str, *args) -> None:
        try:
            getattr(self.signals, signal_name).emit(*args)
        except RuntimeError as exc:
            logger.debug("Skipping worker signal %s after Qt object cleanup: %s", signal_name, exc)

    def run(self) -> None:
        try:
            self._emit("status_changed", "transcribing")
            transcript = transcribe(
                wav_file=self.wav_file,
                model=self.model,
                language=self.language,
                backend=self.backend,
                custom_terms=self.custom_terms,
            )

            if not transcript or not transcript.strip():
                raise TranscribeError("Keine Sprache im Audio erkannt.")

            # LLM rewrite if it is an LLM workflow
            if self.workflow in LLM_WORKFLOWS:
                self._emit("status_changed", "rewriting")
                if not self.llm_service.is_available():
                    raise LLMServiceError(
                        f"OpenAI API-Key nicht gesetzt. Bitte {self.config.openai_api_key_env} in ~/.config/blitztext-linux/secrets.env setzen."
                    )
                result_text = self.llm_service.rewrite(self.workflow, transcript)
            else:
                result_text = transcript

            # Paste
            if self.autopaste:
                self.paste_service.paste(result_text)
            else:
                self.paste_service.clipboard_only(result_text)

            self._emit("result", result_text)
        except Exception as e:
            self._emit("error", str(e))
        finally:
            # Clean up WAV file
            try:
                if self.wav_file.is_file():
                    self.wav_file.unlink()
            except OSError as exc:
                logger.warning("Failed to delete temp WAV file %s: %s", self.wav_file, exc)
            self._emit("finished", self)


class BlitztextApp(QObject):
    """Main Blitztext Linux application coordinator."""

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.config = Config.load()

        self.llm_service = self._build_llm_service()
        self.audio_recorder = AudioRecorder()
        self.paste_service = PasteService(autopaste=self.config.autopaste)

        # State machine state: "IDLE", "RECORDING", "TRANSCRIBING", "LLM_REWRITING"
        self.state = "IDLE"
        self.current_workflow: Optional[WorkflowType] = None
        self._tray_error_message: Optional[str] = None
        self._active_workers: list[_TranscribeWorker] = []

        # Diktat-/Verlauf-/TTS-Zustand
        self._dictation_mode = False
        self._history_panel: Optional[HistoryPanel] = None
        self._tts_window: Optional[TtsWindow] = None
        self._main_window: Optional[MainWindow] = None

        # Tray setup
        self.setup_tray()

        # Start hotkey worker
        self.hotkey_worker: Optional[HotkeyWorker] = None
        self.hotkey_thread: Optional[QThread] = None
        self.start_hotkey_worker()

    def _build_llm_service(self) -> LLMService:
        """Baut den LLMService aus der aktuellen Config.

        Einziger Konstruktionsort, damit Init und Settings-Save nicht
        auseinanderlaufen (z. B. base_url/model vergessen).
        """
        return LLMService(
            api_key=self.config.resolve_openai_api_key(),
            tone=self.config.text_improver_tone,
            emoji_density=self.config.emoji_density,
            dampf_system_prompt=self.config.dampf_system_prompt,
            custom_terms=self.config.custom_terms,
            api_key_env=self.config.openai_api_key_env,
            writing_preset=self.config.writing_preset,
            base_url=self.config.llm_base_url,
            model=self.config.llm_model,
        )

    def setup_tray(self) -> None:
        self.tray_icon = QSystemTrayIcon(self)
        self._tray_icons = {
            "IDLE": self._create_microphone_icon(QColor("#2e7d32")),
            "RECORDING": self._create_microphone_icon(QColor("#c62828")),
            "TRANSCRIBING": self._create_microphone_icon(QColor("#ef6c00")),
            "LLM_REWRITING": self._create_microphone_icon(QColor("#ef6c00")),
            "ERROR": self._create_microphone_icon(QColor("#757575")),
        }

        # Load standard icon fallback
        icon = self._tray_icons["IDLE"]
        if icon.isNull():
            icon = QIcon.fromTheme("audio-input-microphone")
        if icon.isNull():
            icon = self.app.style().standardIcon(QStyle.StandardPixmap.SP_MediaVolume)
        self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip("Blitztext")

        # Show window via single/double click on the tray icon
        self.tray_icon.activated.connect(self._on_tray_activated)

        # Create menu
        self.menu = QMenu()

        # Fenster anzeigen (grafischer Fallback)
        self.action_show_window = QAction("🪟  Fenster anzeigen", self)
        self.action_show_window.triggered.connect(self.show_main_window)
        self.menu.addAction(self.action_show_window)
        self.menu.addSeparator()

        # Actions für die fünf Workflows
        self.action_transcription = QAction("🎙  Blitztext\tMeta+H", self)
        self.action_transcription.triggered.connect(lambda: self._trigger_menu_workflow(WorkflowType.TRANSCRIPTION))
        self.menu.addAction(self.action_transcription)

        self.action_local = QAction("🔒  Blitztext Lokal\tMeta+Shift+H", self)
        self.action_local.triggered.connect(lambda: self._trigger_menu_workflow(WorkflowType.LOCAL))
        self.menu.addAction(self.action_local)

        self.action_improver = QAction("✨  Blitztext+\tMeta+Shift+T", self)
        self.action_improver.triggered.connect(lambda: self._trigger_menu_workflow(WorkflowType.TEXT_IMPROVER))
        self.menu.addAction(self.action_improver)

        self.action_dampf = QAction("🔥  Blitztext $%&!\tMeta+Shift+D", self)
        self.action_dampf.triggered.connect(lambda: self._trigger_menu_workflow(WorkflowType.DAMPF_ABLASSEN))
        self.menu.addAction(self.action_dampf)

        self.action_emoji = QAction("😊  Blitztext :)\tMeta+Shift+E", self)
        self.action_emoji.triggered.connect(lambda: self._trigger_menu_workflow(WorkflowType.EMOJI_TEXT))
        self.menu.addAction(self.action_emoji)

        self.menu.addSeparator()

        # Diktat-Modus (Toggle): sammelt Transkripte als Notizen
        self.action_dictation = QAction("🎤  Diktat-Modus", self)
        self.action_dictation.setCheckable(True)
        self.action_dictation.toggled.connect(self._on_dictation_toggled)
        self.menu.addAction(self.action_dictation)

        # Verlauf anzeigen
        self.action_history = QAction("📋  Verlauf…", self)
        self.action_history.triggered.connect(self.show_history_panel)
        self.menu.addAction(self.action_history)

        # Vorlesen (TTS)
        self.action_tts = QAction("🔊  Vorlesen…", self)
        self.action_tts.triggered.connect(self.show_tts_window)
        self.menu.addAction(self.action_tts)

        self.menu.addSeparator()

        # Settings action
        self.action_settings = QAction("⚙   Einstellungen...", self)
        self.action_settings.triggered.connect(self.show_settings_dialog)
        self.menu.addAction(self.action_settings)

        # Quit action
        self.action_quit = QAction("✕   Beenden", self)
        self.action_quit.triggered.connect(self.quit_app)
        self.menu.addAction(self.action_quit)

        self.tray_icon.setContextMenu(self.menu)

        # Enable/disable items dynamically
        self.update_menu_availability()

        self.tray_icon.show()

    def _create_microphone_icon(self, color: QColor) -> QIcon:
        # In doppelter Aufloesung zeichnen — das Panel skaliert herunter,
        # dadurch bleibt der Glyph auch bei kleinen Tray-Groessen scharf.
        pixmap = QPixmap(128, 128)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(2, 2)
        painter.setPen(QPen(color, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(23, 8, 18, 29, 9, 9)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(15, 23, 34, 25, 200 * 16, 140 * 16)
        painter.drawLine(32, 46, 32, 55)
        painter.drawLine(24, 55, 40, 55)
        painter.end()
        return QIcon(pixmap)

    def update_menu_availability(self) -> None:
        available = self.llm_service.is_available()
        self.action_improver.setEnabled(available)
        self.action_dampf.setEnabled(available)
        self.action_emoji.setEnabled(available)

    def start_hotkey_worker(self) -> None:
        self.stop_hotkey_worker()

        self.hotkey_thread = QThread()
        self.hotkey_worker = HotkeyWorker(
            hotkey_mode=self.config.hotkey_mode,
            transcription_key=self.config.transcription_hotkey,
        )
        self.hotkey_worker.moveToThread(self.hotkey_thread)

        self.hotkey_thread.started.connect(self.hotkey_worker.run)
        self.hotkey_worker.workflow_triggered.connect(self._on_workflow_triggered)
        self.hotkey_worker.recording_stop.connect(self._on_recording_stop)
        self.hotkey_worker.error.connect(self._on_hotkey_error)

        self.hotkey_thread.start()

    def stop_hotkey_worker(self) -> None:
        if self.hotkey_worker:
            self.hotkey_worker.stop()
            self.hotkey_worker = None
        if self.hotkey_thread:
            self.hotkey_thread.quit()
            self.hotkey_thread.wait(2000)
            self.hotkey_thread = None

    def show_settings_dialog(self) -> None:
        dialog = SettingsDialog(self.config)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Update LLM Service parameters from saved configuration
            self.llm_service = self._build_llm_service()
            self.update_menu_availability()

            # Restart hotkey listener if mode or key changed
            if self.hotkey_worker and (
                self.hotkey_worker._mode != self.config.hotkey_mode
                or self.hotkey_worker._transcription_key != self.config.transcription_hotkey
            ):
                logger.info(
                    "Hotkey config changed (mode=%s, key=%s). Restarting hotkey worker.",
                    self.config.hotkey_mode,
                    self.config.transcription_hotkey,
                )
                self.start_hotkey_worker()

    def _trigger_menu_workflow(self, workflow: WorkflowType) -> None:
        self._on_workflow_triggered(workflow)

    @pyqtSlot(object)
    def _on_workflow_triggered(self, workflow: WorkflowType) -> None:
        logger.info("Workflow triggered: %s (current state: %s)", workflow, self.state)

        if self.state == "IDLE":
            self._start_recording(workflow)

        elif self.state == "RECORDING":
            if self.config.hotkey_mode == "toggle":
                if workflow != self.current_workflow:
                    # Any hotkey press stops the active recording — same-key or different-key.
                    # After processing finishes (IDLE), the user can trigger a new workflow.
                    logger.info(
                        "Different workflow %s pressed — stopping active recording %s.",
                        workflow, self.current_workflow,
                    )
                self._stop_recording_and_process()
            else:
                logger.info("Ignored hotkey trigger %s during recording %s in hold mode", workflow, self.current_workflow)

        else:
            logger.info("Ignored hotkey trigger %s while busy", workflow)

    def _start_recording(self, workflow: WorkflowType) -> None:
        try:
            self.audio_recorder.start(device=self.config.audio_device)
            self.current_workflow = workflow
            self._set_state("RECORDING", f"workflow {workflow.value} started")
        except AudioRecorderError as e:
            logger.error("Failed to start recording: %s", e)
            self.show_tray_error("Aufnahme-Fehler", f"Aufnahme konnte nicht gestartet werden: {e}")
            self.current_workflow = None
            self._set_state("IDLE", "recording start failed")

    def gui_toggle_recording(self, workflow: WorkflowType) -> None:
        """Start/Stopp per Maus-Klick — unabhaengig vom Hotkey-Modus.

        Fallback wenn der Hotkey nicht greift oder keine Tastatur zur Hand ist.
        """
        if self.state == "IDLE":
            self._start_recording(workflow)
        elif self.state == "RECORDING":
            self._stop_recording_and_process()
        else:
            logger.info("GUI-Toggle ignoriert (State=%s, busy)", self.state)

    def gui_discard(self) -> None:
        """Laufende Aufnahme verwerfen, ohne zu transkribieren."""
        if self.state == "RECORDING":
            self.audio_recorder.discard()
            self.current_workflow = None
            self._set_state("IDLE", "discarded via gui")

    @pyqtSlot()
    def _on_recording_stop(self) -> None:
        logger.info("Recording stop signal received (current state: %s)", self.state)
        if self.state == "RECORDING":
            if self.config.hotkey_mode == "hold":
                self._stop_recording_and_process()
            else:
                logger.info("Ignored recording stop signal because hotkey mode is toggle")

    def _stop_recording_and_process(self) -> None:
        try:
            wav_path = self.audio_recorder.stop()
            if not wav_path:
                logger.warning("No audio was recorded")
                self.show_tray_warning("Blitztext", "Keine Audioaufnahme erfasst.")
                self.current_workflow = None
                self._set_state("IDLE", "empty recording")
                return

            self._set_state("TRANSCRIBING", "recording stopped")

            # Ensure PasteService has the latest autopaste configuration
            self.paste_service.autopaste = self.config.autopaste

            # Create the transcribe worker
            worker = _TranscribeWorker(
                wav_file=wav_path,
                model=self.config.model,
                language=self.config.language,
                backend=self.config.backend,
                workflow=self.current_workflow,
                llm_service=self.llm_service,
                autopaste=self.config.autopaste,
                paste_service=self.paste_service,
                custom_terms=self.config.custom_terms,
            )

            worker.signals.status_changed.connect(self._on_worker_status_changed)
            worker.signals.result.connect(self._on_worker_result)
            worker.signals.error.connect(self._on_worker_error)
            worker.signals.finished.connect(self._on_worker_finished)

            self._active_workers.append(worker)
            QThreadPool.globalInstance().start(worker)

        except AudioRecorderError as e:
            logger.error("Failed to stop recording: %s", e)
            self.show_tray_error("Aufnahme-Fehler", f"Aufnahme konnte nicht sauber gestoppt werden: {e}")
            self.current_workflow = None
            self._set_state("IDLE", "recording stop failed")

    @pyqtSlot(str)
    def _on_worker_status_changed(self, status: str) -> None:
        if status == "transcribing":
            self._set_state("TRANSCRIBING", "worker status transcribing")
        elif status == "rewriting":
            self._set_state("LLM_REWRITING", "worker status rewriting")
        else:
            self.update_tray_state()

    @pyqtSlot(str)
    def _on_worker_result(self, result_text: str) -> None:
        logger.info("Transcription/Rewrite success. Result length: %d chars", len(result_text))
        self._add_to_history(result_text, is_dictation=self._dictation_mode)
        if self._dictation_mode:
            notify_service.notify(
                "Blitztext Diktat",
                "Eintrag gespeichert ({} Wörter).".format(len(result_text.split())),
            )
        self.current_workflow = None
        self._set_state("IDLE", "worker result")

    @pyqtSlot(str)
    def _on_worker_error(self, err_msg: str) -> None:
        logger.error("Worker error: %s", err_msg)
        self.show_tray_error("Blitztext Fehler", err_msg)
        notify_service.notify("Blitztext Fehler", err_msg, urgency="critical")
        self.current_workflow = None
        self._set_state("IDLE", "worker error", keep_error=True)

    # ------------------------------------------------------------------
    # Diktat / Verlauf / Vorlesen
    # ------------------------------------------------------------------

    def _ensure_history_panel(self) -> HistoryPanel:
        if self._history_panel is None:
            panel = HistoryPanel(
                max_entries=self.config.history_size,
                notes_folder=self.config.notes_folder,
            )
            panel.setWindowTitle("Blitztext – Verlauf")
            panel.resize(320, 440)
            panel.merged.connect(self._on_dictation_merged)
            panel.count_changed.connect(self._on_history_count_changed)
            self._history_panel = panel
        else:
            # Konfiguration aktuell halten
            self._history_panel.notes_folder = self.config.notes_folder
            self._history_panel.set_max_entries(self.config.history_size)
        return self._history_panel

    def _add_to_history(self, text: str, is_dictation: bool) -> None:
        if not text or not text.strip():
            return
        panel = self._ensure_history_panel()
        panel.add_entry(text, is_dictation=is_dictation)

    def show_history_panel(self) -> None:
        panel = self._ensure_history_panel()
        panel.show()
        panel.raise_()
        panel.activateWindow()

    def _on_dictation_toggled(self, enabled: bool) -> None:
        self.set_dictation_mode(enabled)

    def set_dictation_mode(self, enabled: bool) -> None:
        """Zentrale Umschaltung — haelt Tray-Action und Hauptfenster synchron."""
        if self._dictation_mode == enabled:
            return
        self._dictation_mode = enabled
        logger.info("Diktat-Modus %s", "aktiviert" if enabled else "deaktiviert")

        # UI synchron halten, ohne Signale erneut auszuloesen
        self.action_dictation.blockSignals(True)
        self.action_dictation.setChecked(enabled)
        self.action_dictation.blockSignals(False)
        if self._main_window is not None:
            self._main_window.set_dictation_checked(enabled)

        if enabled:
            self._ensure_history_panel()
            self.show_history_panel()
            notify_service.notify(
                "Blitztext Diktat",
                "Diktat-Modus aktiv. Aufnahmen werden als Notizen gesammelt.",
            )

    def _on_dictation_merged(self, path: str) -> None:
        notify_service.notify("Blitztext Diktat", f"Zusammengeführt und gespeichert:\n{path}")

    def show_tts_window(self) -> None:
        if self._tts_window is None:
            self._tts_window = TtsWindow(self.config)
            self._tts_window.finished.connect(self._on_tts_closed)
        self._tts_window.show()
        self._tts_window.raise_()
        self._tts_window.activateWindow()

    def _on_tts_closed(self, _result: int) -> None:
        self._tts_window = None

    def _on_history_count_changed(self, count: int) -> None:
        if self._main_window is not None:
            self._main_window.set_history_count(count)

    # ------------------------------------------------------------------
    # Hauptfenster
    # ------------------------------------------------------------------

    def _ensure_main_window(self) -> MainWindow:
        if self._main_window is None:
            window = MainWindow(self)
            try:
                from app import theme
                window.setWindowIcon(theme.create_app_icon())
            except Exception:  # pragma: no cover - rein kosmetisch
                pass
            window.set_dictation_checked(self._dictation_mode)
            if self._history_panel is not None:
                window.set_history_count(self._history_panel.entry_count)
            window.update_state(self.state, self.current_workflow, self._tray_error_message)
            self._main_window = window
        return self._main_window

    def show_main_window(self) -> None:
        window = self._ensure_main_window()
        window.show()
        window.raise_()
        window.activateWindow()

    @pyqtSlot(QSystemTrayIcon.ActivationReason)
    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_main_window()

    @pyqtSlot(object)
    def _on_worker_finished(self, worker: object) -> None:
        try:
            self._active_workers.remove(worker)
        except ValueError:
            pass

    def _set_state(self, new_state: str, reason: str, keep_error: bool = False) -> None:
        old_state = self.state
        if not keep_error and new_state != "IDLE":
            self._tray_error_message = None
        if old_state != new_state:
            logger.debug("State changed: %s -> %s (%s)", old_state, new_state, reason)
        else:
            logger.debug("State unchanged: %s (%s)", new_state, reason)
        self.state = new_state
        self._on_state_changed()

    def _on_state_changed(self) -> None:
        self.update_tray_state()
        if self._main_window is not None:
            self._main_window.update_state(self.state, self.current_workflow, self._tray_error_message)

    def update_tray_state(self) -> None:
        if self._tray_error_message:
            self.tray_icon.setIcon(self._tray_icons["ERROR"])
            self.tray_icon.setToolTip(f"Blitztext Fehler: {self._tray_error_message}")
        elif self.state == "IDLE":
            self.tray_icon.setIcon(self._tray_icons["IDLE"])
            self.tray_icon.setToolTip("Blitztext")
        elif self.state == "RECORDING":
            self.tray_icon.setIcon(self._tray_icons["RECORDING"])
            wf_name = self.current_workflow.value if self.current_workflow else ""
            self.tray_icon.setToolTip(f"Aufnahme läuft… ({wf_name})")
        elif self.state == "TRANSCRIBING":
            self.tray_icon.setIcon(self._tray_icons["TRANSCRIBING"])
            self.tray_icon.setToolTip("Transkribiere…")
        elif self.state == "LLM_REWRITING":
            self.tray_icon.setIcon(self._tray_icons["LLM_REWRITING"])
            self.tray_icon.setToolTip("Verarbeite mit KI…")

    @pyqtSlot(str)
    def _on_hotkey_error(self, err_msg: str) -> None:
        if _is_hotkey_device_access_error(err_msg):
            logger.warning("Hotkey worker unavailable, continuing with GUI/tray fallback: %s", err_msg)
            self.show_tray_warning(
                "Hotkey Hinweis",
                f"{err_msg}\nStart/Stopp läuft über Fenster/Tray.",
            )
            return

        logger.error("Hotkey worker error: %s", err_msg)
        self.show_tray_error("Hotkey Fehler", err_msg)

    def show_tray_error(self, title: str, message: str) -> None:
        self._tray_error_message = message
        self.update_tray_state()
        self.tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Critical, 10000)

    def show_tray_warning(self, title: str, message: str) -> None:
        self.tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Warning, 5000)

    def quit_app(self) -> None:
        logger.info("Quitting application...")
        self.audio_recorder.discard()
        self.stop_hotkey_worker()
        if self._tts_window is not None:
            self._tts_window.close()
            self._tts_window = None
        if self._history_panel is not None:
            self._history_panel.close()
            self._history_panel = None
        if self._main_window is not None:
            self._main_window.hide()
            self._main_window = None
        self.tray_icon.hide()
        self.app.quit()


def main() -> int:
    """Application entry point."""
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("BLITZTEXT_DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    _require_display_environment()
    _configure_qt_platform()

    try:
        app = QApplication(sys.argv)
    except Exception as exc:
        logging.critical(
            "QApplication init failed (WAYLAND_DISPLAY=%s, DISPLAY=%s): %s",
            os.environ.get("WAYLAND_DISPLAY", "<unset>"),
            os.environ.get("DISPLAY", "<unset>"),
            exc,
        )
        return 1

    app.setApplicationName("Blitztext")
    app.setQuitOnLastWindowClosed(False)

    # Design-System: Glass-Theme + Marken-App-Icon (Mikrofon + Blitz)
    try:
        from app import theme
        theme.apply_theme(app)
        app.setWindowIcon(theme.create_app_icon())
    except Exception as exc:  # pragma: no cover - rein kosmetisch
        logging.warning("Theme/App-Icon konnte nicht angewendet werden: %s", exc)

    blitztext = BlitztextApp(app)
    blitztext.show_main_window()

    exit_code = app.exec()

    blitztext.stop_hotkey_worker()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

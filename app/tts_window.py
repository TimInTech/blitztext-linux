"""Vorlese-Fenster (Text-to-Speech) mit lokalem Piper und optionalem OpenAI Cloud-TTS."""
from __future__ import annotations

import os
import shutil
import signal
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QProcess, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t

PIPER_VENV_PATH = str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "piper")
VOICES_DIR = Path.home() / ".local" / "share" / "piper-voices"
TTS_RUNTIME_DIR = os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir())
OPENAI_TTS_MODEL_DEFAULT = "gpt-4o-mini-tts"
OPENAI_TTS_VOICE_DEFAULT = "marin"
OPENAI_TTS_VOICES = [
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
]
OPENAI_TTS_MODEL_OPTIONS = [OPENAI_TTS_MODEL_DEFAULT, "tts-1", "tts-1-hd"]
OPENAI_TTS_TIMEOUT = 30.0


def _piper_install_hint() -> str:
    return t("tts.error.piper_not_found")


def _openai_tts_install_hint() -> str:
    return t("tts.error.openai_not_available")


def _find_ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg")


def _openai_tts_consent_text() -> str:
    return t("tts.consent.message")


def _scrub_secret(text: str, secret: str) -> str:
    """Entfernt einen API-Key aus Fehlertexten, damit er nie in der UI/Logs erscheint."""
    if secret and text:
        return text.replace(secret, "***")
    return text


def _find_piper() -> Optional[str]:
    if os.path.isfile(PIPER_VENV_PATH) and os.access(PIPER_VENV_PATH, os.X_OK):
        return PIPER_VENV_PATH
    return shutil.which("piper")


def is_piper_available() -> bool:
    return _find_piper() is not None


def list_voices() -> list[tuple[str, str]]:
    """Gibt eine Liste (Label, voller .onnx-Pfad) aus VOICES_DIR zurueck."""
    voices: list[tuple[str, str]] = []
    if not VOICES_DIR.is_dir():
        return voices
    for f in sorted(VOICES_DIR.glob("*.onnx")):
        voices.append((f.name, str(f)))
    return voices


def list_openai_voices() -> list[str]:
    return list(OPENAI_TTS_VOICES)


def _tts_speed_to_openai_speed(speed: float) -> float:
    speed = max(0.5, min(2.0, float(speed)))
    return round(1.0 / speed, 3)


def _playback_command(wav_path: str) -> tuple[str, list[str]]:
    if shutil.which("paplay"):
        return "paplay", [wav_path]
    return "aplay", ["-D", "pipewire", wav_path]


def _build_ffmpeg_export_command(input_wav: str, output_path: str, ffmpeg_path: Optional[str] = None) -> tuple[str, list[str]]:
    program = ffmpeg_path or _find_ffmpeg() or "ffmpeg"
    suffix = Path(output_path).suffix.lower()
    if suffix in {".ogg", ".opus"}:
        args = [
            "-y",
            "-i", input_wav,
            "-vn",
            "-c:a", "libopus",
            "-b:a", "32k",
            output_path,
        ]
    elif suffix == ".mp3":
        args = [
            "-y",
            "-i", input_wav,
            "-vn",
            "-c:a", "libmp3lame",
            "-q:a", "4",
            output_path,
        ]
    else:
        raise ValueError(f"unsupported export format: {suffix or '(none)'}")
    return program, args


def _safe_unlink(path: Optional[str]) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _make_tts_wav_path() -> str:
    fd, path = tempfile.mkstemp(prefix="blitztext-tts-", suffix=".wav", dir=TTS_RUNTIME_DIR)
    os.close(fd)
    _safe_unlink(path)
    return path


def _make_export_temp_path(output_path: str) -> str:
    target = Path(output_path)
    fd, temp_path = tempfile.mkstemp(
        prefix=f".{target.stem}.blitztext-",
        suffix=target.suffix,
        dir=str(target.parent),
    )
    os.close(fd)
    _safe_unlink(temp_path)
    return temp_path


def _normalize_export_path(selected_path: str, selected_filter: str) -> str:
    path = Path(selected_path)
    if path.suffix:
        return str(path)

    normalized_filter = selected_filter.lower()
    if "mp3" in normalized_filter and "ogg" not in normalized_filter and "opus" not in normalized_filter:
        return str(path.with_suffix(".mp3"))
    if "opus" in normalized_filter and "ogg" not in normalized_filter:
        return str(path.with_suffix(".opus"))
    return str(path.with_suffix(".ogg"))


class CloudTtsServiceError(Exception):
    """Raised when OpenAI Cloud-TTS cannot be synthesized."""


class CloudTtsService:
    def __init__(self, config, client: Optional[object] = None) -> None:
        self.config = config
        self.api_key = config.resolve_openai_api_key()
        self.api_key_env = config.openai_api_key_env
        self._openai_installed = True
        self.client = client
        if client is not None:
            return
        if not self.api_key:
            self.client = None
            return
        try:
            import openai
        except ImportError:
            self._openai_installed = False
            self.client = None
        else:
            self.client = openai.OpenAI(api_key=self.api_key)

    def is_available(self) -> bool:
        return self.config.tts_provider == "openai" and bool(self.api_key) and self.client is not None

    def _missing_key_message(self) -> str:
        return (
            f"OpenAI API-Key nicht gesetzt. Bitte die Umgebungsvariable "
            f"{self.api_key_env} in ~/.config/blitztext-linux/secrets.env setzen."
        )

    def _missing_openai_package_message(self) -> str:
        return "Python-Paket openai fehlt. Bitte installieren: pip install openai"

    def _check_ready(self) -> None:
        if self.config.tts_provider != "openai":
            raise CloudTtsServiceError("OpenAI Cloud-TTS ist nicht aktiviert.")
        if not self.api_key:
            raise CloudTtsServiceError(self._missing_key_message())
        if not self._openai_installed or self.client is None:
            raise CloudTtsServiceError(self._missing_openai_package_message())

    def synthesize(self, text: str, output_path: Optional[str] = None) -> str:
        self._check_ready()
        if not text or not text.strip():
            raise ValueError("text must not be empty")
        if output_path is None:
            output_path = _make_tts_wav_path()

        response = self.client.audio.speech.create(
            model=self.config.tts_openai_model,
            voice=self.config.tts_openai_voice,
            input=text.strip(),
            response_format="wav",
            speed=_tts_speed_to_openai_speed(self.config.tts_speed),
            timeout=OPENAI_TTS_TIMEOUT,
        )

        if hasattr(response, "stream_to_file"):
            response.stream_to_file(output_path)
        elif hasattr(response, "write_to_file"):
            response.write_to_file(output_path)
        else:
            data = None
            if hasattr(response, "read"):
                data = response.read()
            elif hasattr(response, "content"):
                data = response.content
            elif hasattr(response, "body"):
                data = response.body
            if data is None:
                raise CloudTtsServiceError("OpenAI-Antwort kann nicht in eine Datei geschrieben werden.")
            if isinstance(data, str):
                data = data.encode("utf-8")
            Path(output_path).write_bytes(data)
        return output_path


class _CloudTtsWorker(QObject):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, service: CloudTtsService, text: str, output_path: str) -> None:
        super().__init__()
        self._service = service
        self._text = text
        self._output_path = output_path
        self._cancelled = False

    def request_cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        try:
            if self._cancelled or QThread.currentThread().isInterruptionRequested():
                return
            result = self._service.synthesize(self._text, output_path=self._output_path)
            if self._cancelled or QThread.currentThread().isInterruptionRequested():
                try:
                    Path(result).unlink(missing_ok=True)
                except OSError:
                    pass
                return
            self.finished.emit(result)
        except Exception as exc:  # pragma: no cover - defensive
            if not self._cancelled:
                secret = getattr(self._service, "api_key", "")
                self.error.emit(_scrub_secret(str(exc), secret))


class TtsWindow(QDialog):
    """Text -> TTS. Non-blocking via QProcess bzw. QThread, mit Abbruch + Stimmenwahl."""

    def __init__(self, config, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle(t("tts.window_title"))
        self.resize(430, 340)
        self._piper_proc: Optional[QProcess] = None
        self._aplay_proc: Optional[QProcess] = None
        self._export_proc: Optional[QProcess] = None
        self._cloud_thread: Optional[QThread] = None
        self._cloud_worker: Optional[_CloudTtsWorker] = None
        # Noch laufende, vom Dialog geloeste Cloud-Threads bis 'finished' referenziert
        # halten, damit PyQt keinen laufenden QThread zerstoert ("destroyed while running").
        self._detached_cloud_threads: list[QThread] = []
        self._piper_path = _find_piper()
        self._last_tts_text = ""
        self._pending_export_path: Optional[str] = None
        self._active_wav_path: Optional[str] = None
        self._export_temp_path: Optional[str] = None
        self._is_paused = False
        self._setup_ui()
        self._populate_voices()
        self._refresh_status_hint()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self._text_edit = QTextEdit()
        self._text_edit.setPlaceholderText(t("tts.text.placeholder"))
        layout.addWidget(self._text_edit, 1)

        provider_row = QHBoxLayout()
        provider_row.setSpacing(6)
        provider_row.addWidget(QLabel(t("tts.provider.label")))
        self._provider_combo = QComboBox()
        self._provider_combo.addItem(t("tts.provider.piper_local"), "piper")
        self._provider_combo.addItem(t("tts.provider.openai_cloud"), "openai")
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_row.addWidget(self._provider_combo, 1)
        layout.addLayout(provider_row)

        voice_row = QHBoxLayout()
        voice_row.setSpacing(6)
        voice_row.addWidget(QLabel(t("tts.voice.label")))
        self._voice_combo = QComboBox()
        self._voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        voice_row.addWidget(self._voice_combo, 1)
        layout.addLayout(voice_row)

        model_row = QHBoxLayout()
        model_row.setSpacing(6)
        model_row.addWidget(QLabel(t("tts.model.label")))
        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText(OPENAI_TTS_MODEL_DEFAULT)
        self._model_edit.editingFinished.connect(self._on_model_changed)
        model_row.addWidget(self._model_edit, 1)
        layout.addLayout(model_row)

        speed_row = QHBoxLayout()
        speed_row.setSpacing(6)
        speed_row.addWidget(QLabel(t("tts.speed.label")))
        self._speed_combo = QComboBox()
        self._speed_combo.addItem(t("tts.speed.very_fast"), 0.6)
        self._speed_combo.addItem(t("tts.speed.fast"), 0.8)
        self._speed_combo.addItem(t("tts.speed.normal"), 1.0)
        self._speed_combo.addItem(t("tts.speed.slow"), 1.25)
        self._speed_combo.addItem(t("tts.speed.very_slow"), 1.5)
        saved_speed = float(self._config.tts_speed)
        idx = self._speed_combo.findData(saved_speed)
        self._speed_combo.setCurrentIndex(idx if idx >= 0 else 2)
        self._speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        speed_row.addWidget(self._speed_combo)
        layout.addLayout(speed_row)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._btn_close = QPushButton(t("tts.button.close"))
        self._btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self._btn_close)

        self._btn_replay = QPushButton(t("tts.button.replay"))
        self._btn_replay.clicked.connect(self._on_replay_clicked)
        self._btn_replay.setEnabled(False)
        btn_row.addWidget(self._btn_replay)

        self._btn_export = QPushButton(t("tts.button.export"))
        self._btn_export.clicked.connect(self._on_export_clicked)
        btn_row.addWidget(self._btn_export)

        self._btn_pause = QPushButton(t("tts.button.pause"))
        self._btn_pause.clicked.connect(self._on_pause_clicked)
        self._btn_pause.setEnabled(False)
        btn_row.addWidget(self._btn_pause)

        self._btn_speak = QPushButton(t("tts.button.speak"))
        self._btn_speak.clicked.connect(self._on_speak_clicked)
        btn_row.addWidget(self._btn_speak)

        layout.addLayout(btn_row)

        self._provider_combo.setCurrentIndex(0 if self._config.tts_provider == "piper" else 1)
        self._model_edit.setText(self._config.tts_openai_model)

    def set_text(self, text: str) -> None:
        self._text_edit.setPlainText(text)

    def _populate_voices(self) -> None:
        provider = self._current_provider()
        self._voice_combo.blockSignals(True)
        self._voice_combo.clear()

        if provider == "openai":
            for voice in list_openai_voices():
                self._voice_combo.addItem(voice, userData=voice)
            selected = self._voice_combo.findData(self._config.tts_openai_voice)
            self._voice_combo.setCurrentIndex(selected if selected >= 0 else self._voice_combo.findData(OPENAI_TTS_VOICE_DEFAULT))
            self._voice_combo.setEnabled(True)
        else:
            voices = list_voices()
            if not voices:
                self._voice_combo.addItem(t("tts.voice.none_found"))
                self._voice_combo.setEnabled(False)
            else:
                for label, path in voices:
                    self._voice_combo.addItem(label, userData=path)
                selected = self._voice_combo.findData(self._config.tts_voice)
                self._voice_combo.setCurrentIndex(selected if selected >= 0 else 0)
                self._voice_combo.setEnabled(True)

        self._voice_combo.blockSignals(False)
        self._model_edit.setEnabled(provider == "openai")
        self._speed_combo.setEnabled(True)
        self._update_speak_button_state()

    def _refresh_status_hint(self) -> None:
        provider = self._current_provider()
        if provider == "openai":
            service = CloudTtsService(self._config)
            if service.is_available():
                self._status_label.setText(t("tts.status.openai_ready"))
                self._status_label.setStyleSheet("color: #4caf50;")
            else:
                self._status_label.setText(_openai_tts_install_hint())
                self._status_label.setStyleSheet("color: #f44336;")
        else:
            if self._piper_path:
                self._status_label.setText(t("tts.status.piper_ready"))
                self._status_label.setStyleSheet("color: #4caf50;")
            else:
                self._status_label.setText(_piper_install_hint())
                self._status_label.setStyleSheet("color: #f44336;")
        self._update_speak_button_state()

    def _update_speak_button_state(self) -> None:
        provider = self._current_provider()
        if provider == "openai":
            can_synthesize = CloudTtsService(self._config).is_available() or self._cloud_is_running()
        else:
            can_synthesize = bool(self._piper_path) or self._cloud_is_running()
        self._btn_speak.setEnabled(can_synthesize or self._is_speaking())
        self._btn_export.setEnabled(can_synthesize and not self._is_speaking())

    def _current_provider(self) -> str:
        provider = self._provider_combo.currentData()
        return provider if isinstance(provider, str) else "piper"

    def _current_voice(self) -> str:
        voice = self._voice_combo.currentData()
        if isinstance(voice, str) and voice:
            return voice
        if self._current_provider() == "openai":
            return self._config.tts_openai_voice
        voices = list_voices()
        return voices[0][1] if voices else ""

    def _current_tts_text(self) -> str:
        return self._text_edit.toPlainText().strip()

    def _cleanup_active_wav(self) -> None:
        _safe_unlink(self._active_wav_path)
        self._active_wav_path = None

    def _cleanup_export_temp(self) -> None:
        _safe_unlink(self._export_temp_path)
        self._export_temp_path = None

    def _prepare_new_tts_job(self) -> str:
        self._cleanup_active_wav()
        self._cleanup_export_temp()
        wav_path = _make_tts_wav_path()
        self._active_wav_path = wav_path
        return wav_path

    def _current_wav_path(self) -> Optional[str]:
        return self._active_wav_path

    def _cloud_is_running(self) -> bool:
        return self._cloud_thread is not None and self._cloud_thread.isRunning()

    def _ensure_openai_consent(self) -> bool:
        """Einmalige Datenschutz-Bestaetigung fuer Cloud-TTS. True, wenn erteilt."""
        if self._config.tts_openai_consent:
            return True
        answer = QMessageBox.question(
            self,
            t("tts.consent.title"),
            _openai_tts_consent_text(),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self._config.tts_openai_consent = True
        try:
            self._config.save()
        except Exception:
            pass
        return True

    def _revert_provider_to_piper(self) -> None:
        self._provider_combo.blockSignals(True)
        self._provider_combo.setCurrentIndex(0)
        self._provider_combo.blockSignals(False)
        if self._config.tts_provider != "piper":
            self._config.tts_provider = "piper"
            try:
                self._config.save()
            except Exception:
                pass

    @pyqtSlot(int)
    def _on_provider_changed(self, _idx: int) -> None:
        provider = self._current_provider()
        if provider == "openai" and not self._ensure_openai_consent():
            self._revert_provider_to_piper()
            self._populate_voices()
            self._refresh_status_hint()
            return
        if self._config.tts_provider != provider:
            self._config.tts_provider = provider
            try:
                self._config.save()
            except Exception:
                pass
        self._populate_voices()
        self._refresh_status_hint()

    @pyqtSlot(int)
    def _on_voice_changed(self, _idx: int) -> None:
        voice = self._voice_combo.currentData()
        provider = self._current_provider()
        if provider == "openai":
            if isinstance(voice, str) and voice and self._config.tts_openai_voice != voice:
                self._config.tts_openai_voice = voice
                try:
                    self._config.save()
                except Exception:
                    pass
        else:
            if isinstance(voice, str) and voice and self._config.tts_voice != voice:
                self._config.tts_voice = voice
                try:
                    self._config.save()
                except Exception:
                    pass
        self._refresh_status_hint()

    def _on_model_changed(self) -> None:
        model = self._model_edit.text().strip() or OPENAI_TTS_MODEL_DEFAULT
        if self._config.tts_openai_model != model:
            self._config.tts_openai_model = model
            try:
                self._config.save()
            except Exception:
                pass
        self._refresh_status_hint()

    @pyqtSlot(int)
    def _on_speed_changed(self, _idx: int) -> None:
        speed = self._speed_combo.currentData()
        if not isinstance(speed, float):
            return
        if self._config.tts_speed == speed:
            return
        try:
            self._config.tts_speed = speed
            self._config.save()
        except Exception:
            pass

    def _is_speaking(self) -> bool:
        for proc in (self._piper_proc, self._aplay_proc, self._export_proc):
            if proc is not None and proc.state() != QProcess.ProcessState.NotRunning:
                return True
        return self._cloud_is_running()

    @pyqtSlot()
    def _on_speak_clicked(self) -> None:
        if self._is_speaking():
            self._stop_tts()
            return
        self._pending_export_path = None
        self._start_tts()

    @pyqtSlot()
    def _on_replay_clicked(self) -> None:
        if not self._last_tts_text:
            return
        if self._is_speaking():
            self._stop_tts()
        self._pending_export_path = None
        self._start_tts(text=self._last_tts_text)

    @pyqtSlot()
    def _on_export_clicked(self) -> None:
        if self._is_speaking():
            return
        text = self._current_tts_text()
        if not text:
            self._status_label.setText(t("tts.status.no_text"))
            self._status_label.setStyleSheet("color: #f44336;")
            return
        if not _find_ffmpeg():
            self._status_label.setText(t("tts.status.export_ffmpeg_missing"))
            self._status_label.setStyleSheet("color: #f44336;")
            QTimer.singleShot(2500, self._clear_status)
            return
        default_name = t("tts.export.default_filename_prefix") + datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".ogg"
        suggested_path = str(Path.home() / default_name)
        selected_path, selected_filter = QFileDialog.getSaveFileName(
            self,
            t("tts.export.dialog_title"),
            suggested_path,
            "Audio (*.ogg *.opus *.mp3);;Ogg (*.ogg);;Opus (*.opus);;MP3 (*.mp3)",
        )
        if not selected_path:
            return
        self._pending_export_path = _normalize_export_path(selected_path, selected_filter)
        self._start_tts(text=text)

    @pyqtSlot()
    def _on_pause_clicked(self) -> None:
        if not self._aplay_proc or self._aplay_proc.state() == QProcess.ProcessState.NotRunning:
            return
        pid = self._aplay_proc.processId()
        if not pid:
            return
        try:
            if self._is_paused:
                os.kill(pid, signal.SIGCONT)
                self._is_paused = False
                self._btn_pause.setText(t("tts.button.pause"))
                self._status_label.setText(t("tts.status.playback"))
            else:
                os.kill(pid, signal.SIGSTOP)
                self._is_paused = True
                self._btn_pause.setText(t("tts.button.resume"))
                self._status_label.setText(t("tts.status.paused"))
        except OSError:
            pass

    def _start_tts(self, text: Optional[str] = None) -> None:
        if text is None:
            text = self._current_tts_text()
        if not text:
            self._status_label.setText(t("tts.status.no_text"))
            self._status_label.setStyleSheet("color: #f44336;")
            return
        self._last_tts_text = text
        self._btn_replay.setEnabled(True)

        provider = self._current_provider()
        if provider == "openai":
            self._start_cloud_tts(text)
        else:
            self._start_piper_tts(text)

    def _start_piper_tts(self, text: str) -> None:
        if not self._piper_path:
            self._status_label.setText(_piper_install_hint())
            self._status_label.setStyleSheet("color: #f44336;")
            return

        model_path = self._current_voice()
        if not model_path:
            self._status_label.setText(t("tts.status.no_voice_path"))
            self._status_label.setStyleSheet("color: #f44336;")
            return

        wav_path = self._prepare_new_tts_job()
        proc = QProcess(self)
        proc.setProgram(self._piper_path)
        proc.setArguments([
            "--model", model_path,
            "--length_scale", str(float(self._config.tts_speed)),
            "--output_file", wav_path,
        ])
        proc.finished.connect(self._on_piper_finished)
        proc.errorOccurred.connect(self._on_tts_error)
        self._piper_proc = proc

        self._status_label.setText(t("tts.status.synthesis"))
        self._status_label.setStyleSheet("")
        self._btn_speak.setText(t("tts.button.stop"))
        self._update_speak_button_state()

        proc.start()
        proc.write(text.encode("utf-8"))
        proc.closeWriteChannel()

    def _start_cloud_tts(self, text: str) -> None:
        if not self._config.tts_openai_consent:
            self._status_label.setText(t("tts.status.openai_not_confirmed"))
            self._status_label.setStyleSheet("color: #f44336;")
            self._update_speak_button_state()
            return
        service = CloudTtsService(self._config)
        if not service.is_available():
            self._status_label.setText(_openai_tts_install_hint())
            self._status_label.setStyleSheet("color: #f44336;")
            self._update_speak_button_state()
            return

        wav_path = self._prepare_new_tts_job()
        thread = QThread(self)
        worker = _CloudTtsWorker(service, text, wav_path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_cloud_finished)
        worker.error.connect(self._on_cloud_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_cloud_thread_finished)
        self._cloud_thread = thread
        self._cloud_worker = worker

        self._status_label.setText(t("tts.status.cloud_synthesis"))
        self._status_label.setStyleSheet("")
        self._btn_speak.setText(t("tts.button.stop"))
        self._btn_pause.setEnabled(False)
        thread.start()
        self._update_speak_button_state()

    def _start_export_process(self, input_wav: str) -> None:
        output_path = self._pending_export_path
        ffmpeg_path = _find_ffmpeg()
        if not output_path or not ffmpeg_path:
            self._cleanup_export_temp()
            self._cleanup_active_wav()
            self._pending_export_path = None
            self._status_label.setText(t("tts.status.export_ffmpeg_missing"))
            self._status_label.setStyleSheet("color: #f44336;")
            self._btn_speak.setText(t("tts.button.speak"))
            self._btn_pause.setEnabled(False)
            self._is_paused = False
            self._btn_pause.setText(t("tts.button.pause"))
            self._update_speak_button_state()
            clear_status = getattr(self, "_clear_status", None)
            if callable(clear_status):
                QTimer.singleShot(2500, clear_status)
            return

        try:
            export_temp_path = _make_export_temp_path(output_path)
            program, args = _build_ffmpeg_export_command(input_wav, export_temp_path, ffmpeg_path=ffmpeg_path)
        except ValueError:
            self._cleanup_export_temp()
            self._cleanup_active_wav()
            self._pending_export_path = None
            self._status_label.setText(t("tts.status.export_format_unsupported"))
            self._status_label.setStyleSheet("color: #f44336;")
            self._btn_speak.setText(t("tts.button.speak"))
            self._btn_pause.setEnabled(False)
            self._is_paused = False
            self._btn_pause.setText(t("tts.button.pause"))
            self._update_speak_button_state()
            clear_status = getattr(self, "_clear_status", None)
            if callable(clear_status):
                QTimer.singleShot(2500, clear_status)
            return
        except OSError as exc:
            self._cleanup_export_temp()
            self._cleanup_active_wav()
            self._pending_export_path = None
            self._status_label.setText(t("tts.status.error").format(message=str(exc)))
            self._status_label.setStyleSheet("color: #f44336;")
            self._btn_speak.setText(t("tts.button.speak"))
            self._btn_pause.setEnabled(False)
            self._is_paused = False
            self._btn_pause.setText(t("tts.button.pause"))
            self._update_speak_button_state()
            clear_status = getattr(self, "_clear_status", None)
            if callable(clear_status):
                QTimer.singleShot(2500, clear_status)
            return

        self._cleanup_export_temp()
        self._export_temp_path = export_temp_path
        export_proc = QProcess(self)
        export_proc.setProgram(program)
        export_proc.setArguments(args)
        export_proc.finished.connect(self._on_export_finished)
        export_proc.errorOccurred.connect(self._on_tts_error)
        self._export_proc = export_proc

        self._status_label.setText(t("tts.status.exporting"))
        self._status_label.setStyleSheet("")
        self._btn_speak.setText(t("tts.button.stop"))
        self._btn_pause.setEnabled(False)
        self._is_paused = False
        self._btn_pause.setText(t("tts.button.pause"))
        self._update_speak_button_state()
        export_proc.start()

    def _stop_tts(self) -> None:
        for attr in ("_piper_proc", "_aplay_proc", "_export_proc"):
            proc = getattr(self, attr, None)
            if proc is None:
                continue
            for sig in ("finished", "errorOccurred"):
                try:
                    getattr(proc, sig).disconnect()
                except TypeError:
                    pass
            try:
                if attr == "_aplay_proc" and self._is_paused:
                    pid = proc.processId()
                    if pid:
                        try:
                            os.kill(pid, signal.SIGCONT)
                        except OSError:
                            pass
                proc.terminate()
                if not proc.waitForFinished(500):
                    proc.kill()
                    proc.waitForFinished(500)
            except Exception:
                pass
            proc.deleteLater()
            setattr(self, attr, None)

        self._detach_cloud_thread()
        self._cleanup_export_temp()
        self._cleanup_active_wav()
        self._pending_export_path = None

        self._btn_speak.setText(t("tts.button.speak"))
        self._btn_pause.setEnabled(False)
        self._is_paused = False
        self._btn_pause.setText(t("tts.button.pause"))
        self._status_label.setText(t("tts.status.cancelled"))
        self._status_label.setStyleSheet("color: #ff9800;")
        self._update_speak_button_state()
        QTimer.singleShot(2000, self._clear_status)

    def _cleanup_cloud_state(self) -> None:
        self._cloud_worker = None
        self._cloud_thread = None

    def _detach_cloud_thread(self) -> None:
        """Bricht den Cloud-Thread ab. Beendet er sich nicht rechtzeitig (blockierender
        Netzwerkaufruf), wird er vom Dialog entkoppelt, aber bis 'finished' in
        ``self._detached_cloud_threads`` referenziert gehalten -- sonst koennte PyQt den
        noch laufenden QThread zerstoeren ("destroyed while running"). Idempotent: nach dem
        Detach ist der aktive Slot None, ein erneuter Aufruf ist ein No-op."""
        worker = self._cloud_worker
        thread = self._cloud_thread
        if worker is not None:
            worker.request_cancel()
        if thread is not None:
            thread.requestInterruption()
            thread.quit()
            if not thread.wait(1500):
                # Thread haengt noch (z. B. im Netzwerkaufruf): vom Dialog loesen und
                # referenziert halten, bis er 'finished' meldet. Erst dann deleteLater.
                try:
                    thread.setParent(None)
                except Exception:
                    pass
                # Worker am Thread festhalten, damit auch seine Python-Referenz bleibt.
                thread._detached_worker = worker  # type: ignore[attr-defined]
                self._detached_cloud_threads.append(thread)
                thread.finished.connect(
                    lambda t=thread: self._on_detached_thread_finished(t)
                )
        self._cleanup_cloud_state()

    def _on_detached_thread_finished(self, thread: QThread) -> None:
        """Gibt einen detachten Cloud-Thread erst frei, nachdem er wirklich beendet ist."""
        self._detached_cloud_threads = [
            t for t in self._detached_cloud_threads if t is not thread
        ]
        thread.deleteLater()

    @pyqtSlot(str)
    def _on_cloud_finished(self, wav_path: str) -> None:
        self._cleanup_cloud_state()
        if self._pending_export_path:
            self._start_export_process(wav_path)
            return
        self._status_label.setText(t("tts.status.playback"))
        program, args = _playback_command(wav_path)
        aplay = QProcess(self)
        aplay.setProgram(program)
        aplay.setArguments(args)
        aplay.finished.connect(self._on_aplay_finished)
        aplay.errorOccurred.connect(self._on_tts_error)
        self._aplay_proc = aplay
        self._is_paused = False
        self._btn_pause.setText(t("tts.button.pause"))
        self._btn_pause.setEnabled(True)
        self._btn_speak.setText(t("tts.button.stop"))
        aplay.start()

    @pyqtSlot(str)
    def _on_cloud_error(self, message: str) -> None:
        self._cleanup_cloud_state()
        self._cleanup_export_temp()
        self._cleanup_active_wav()
        self._status_label.setText(t("tts.status.error").format(message=message))
        self._status_label.setStyleSheet("color: #f44336;")
        self._btn_speak.setText(t("tts.button.speak"))
        self._btn_pause.setEnabled(False)
        self._is_paused = False
        self._btn_pause.setText(t("tts.button.pause"))
        self._update_speak_button_state()
        QTimer.singleShot(2500, self._clear_status)

    def _on_cloud_thread_finished(self) -> None:
        self._cleanup_cloud_state()
        self._update_speak_button_state()

    @pyqtSlot(int, QProcess.ExitStatus)
    def _on_piper_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        proc = self._piper_proc
        wav_path = self._current_wav_path()
        self._piper_proc = None

        if exit_status != QProcess.ExitStatus.NormalExit or exit_code != 0:
            stderr = ""
            if proc is not None:
                stderr = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()
                proc.deleteLater()
            self._cleanup_export_temp()
            self._cleanup_active_wav()
            msg = stderr or f"Exit {exit_code}"
            self._status_label.setText(t("tts.status.error").format(message=msg))
            self._status_label.setStyleSheet("color: #f44336;")
            self._btn_speak.setText(t("tts.button.speak"))
            self._update_speak_button_state()
            QTimer.singleShot(2500, self._clear_status)
            return
        if proc is not None:
            proc.deleteLater()

        if self._pending_export_path and wav_path:
            self._start_export_process(wav_path)
            return

        if not wav_path:
            self._status_label.setText(t("tts.status.error").format(message=t("tts.status.missing_wav_output")))
            self._status_label.setStyleSheet("color: #f44336;")
            self._btn_speak.setText(t("tts.button.speak"))
            self._update_speak_button_state()
            QTimer.singleShot(2500, self._clear_status)
            return

        self._status_label.setText(t("tts.status.playback"))
        program, args = _playback_command(wav_path)
        aplay = QProcess(self)
        aplay.setProgram(program)
        aplay.setArguments(args)
        aplay.finished.connect(self._on_aplay_finished)
        aplay.errorOccurred.connect(self._on_tts_error)
        self._aplay_proc = aplay
        self._is_paused = False
        self._btn_pause.setText(t("tts.button.pause"))
        self._btn_pause.setEnabled(True)
        aplay.start()

    @pyqtSlot(int, QProcess.ExitStatus)
    def _on_aplay_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        proc = self._aplay_proc
        self._aplay_proc = None
        self._btn_speak.setText(t("tts.button.speak"))
        self._btn_pause.setEnabled(False)
        self._is_paused = False
        self._btn_pause.setText(t("tts.button.pause"))
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            self._status_label.setText(t("tts.status.done"))
            self._status_label.setStyleSheet("color: #4caf50;")
        else:
            stderr = ""
            if proc is not None:
                stderr = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()
            msg = stderr or f"Exit {exit_code}"
            self._status_label.setText(t("tts.status.error").format(message=msg))
            self._status_label.setStyleSheet("color: #f44336;")
        if proc is not None:
            proc.deleteLater()
        self._cleanup_export_temp()
        self._cleanup_active_wav()
        self._update_speak_button_state()
        QTimer.singleShot(2500, self._clear_status)

    @pyqtSlot(int, QProcess.ExitStatus)
    def _on_export_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        proc = self._export_proc
        export_temp_path = self._export_temp_path
        output_path = self._pending_export_path
        self._export_proc = None
        self._btn_speak.setText(t("tts.button.speak"))
        self._btn_pause.setEnabled(False)
        self._is_paused = False
        self._btn_pause.setText(t("tts.button.pause"))
        self._pending_export_path = None
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0 and export_temp_path and output_path:
            try:
                os.replace(export_temp_path, output_path)
                self._status_label.setText(t("tts.status.export_done"))
                self._status_label.setStyleSheet("color: #4caf50;")
                self._export_temp_path = None
            except OSError as exc:
                self._status_label.setText(t("tts.status.error").format(message=str(exc)))
                self._status_label.setStyleSheet("color: #f44336;")
                self._cleanup_export_temp()
        else:
            stderr = ""
            if proc is not None:
                stderr = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()
            msg = stderr or f"Exit {exit_code}"
            self._status_label.setText(t("tts.status.error").format(message=msg))
            self._status_label.setStyleSheet("color: #f44336;")
            self._cleanup_export_temp()
        if proc is not None:
            proc.deleteLater()
        self._cleanup_active_wav()
        self._update_speak_button_state()
        QTimer.singleShot(2500, self._clear_status)

    @pyqtSlot(QProcess.ProcessError)
    def _on_tts_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            if self._export_proc is not None or self._pending_export_path:
                self._status_label.setText(t("tts.status.export_ffmpeg_missing"))
            else:
                self._status_label.setText(_piper_install_hint() if self._current_provider() == "piper" else _openai_tts_install_hint())
        else:
            self._status_label.setText(t("tts.status.error").format(message=error.name))
        self._status_label.setStyleSheet("color: #f44336;")
        self._btn_speak.setText(t("tts.button.speak"))
        self._btn_pause.setEnabled(False)
        self._is_paused = False
        self._btn_pause.setText(t("tts.button.pause"))
        self._pending_export_path = None
        for attr in ("_piper_proc", "_aplay_proc", "_export_proc"):
            proc = getattr(self, attr, None)
            if proc is not None:
                proc.deleteLater()
                setattr(self, attr, None)
        self._cleanup_export_temp()
        self._cleanup_active_wav()
        self._update_speak_button_state()

    def _clear_status(self) -> None:
        if not self._is_speaking():
            self._refresh_status_hint()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._is_speaking():
            self._stop_tts()
        # Sicherstellen, dass kein Cloud-Thread mehr am Dialog haengt, bevor er zerstoert wird.
        self._detach_cloud_thread()
        super().closeEvent(event)

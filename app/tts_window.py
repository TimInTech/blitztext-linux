"""Vorlese-Fenster (Text-to-Speech) mit lokalem Piper und optionalem OpenAI Cloud-TTS."""
from __future__ import annotations

import os
import shutil
import signal
import tempfile
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QProcess, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

PIPER_VENV_PATH = str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "piper")
VOICES_DIR = Path.home() / ".local" / "share" / "piper-voices"
TTS_WAV = os.path.join(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir()), "blitztext-tts.wav")
PIPER_INSTALL_HINT = (
    "Piper nicht gefunden. Installieren: pip install piper-tts und Stimmen nach "
    "~/.local/share/piper-voices legen."
)
OPENAI_TTS_INSTALL_HINT = (
    "OpenAI Cloud-TTS ist nicht verfuegbar. Bitte OPENAI_API_KEY in "
    "~/.config/blitztext-linux/secrets.env setzen."
)
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
OPENAI_TTS_CONSENT_TEXT = (
    "OpenAI Cloud-TTS sendet den eingegebenen Text zur Sprachsynthese an die "
    "OpenAI-Server. Lokale Texte verlassen damit deinen Rechner.\n\n"
    "Moechtest du Cloud-TTS aktivieren?"
)


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

    def synthesize(self, text: str, output_path: str = TTS_WAV) -> str:
        self._check_ready()
        if not text or not text.strip():
            raise ValueError("text must not be empty")

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
        self.setWindowTitle("Vorlesen")
        self.resize(430, 340)
        self._piper_proc: Optional[QProcess] = None
        self._aplay_proc: Optional[QProcess] = None
        self._cloud_thread: Optional[QThread] = None
        self._cloud_worker: Optional[_CloudTtsWorker] = None
        # Noch laufende, vom Dialog geloeste Cloud-Threads bis 'finished' referenziert
        # halten, damit PyQt keinen laufenden QThread zerstoert ("destroyed while running").
        self._detached_cloud_threads: list[QThread] = []
        self._piper_path = _find_piper()
        self._last_tts_text = ""
        self._is_paused = False
        self._setup_ui()
        self._populate_voices()
        self._refresh_status_hint()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self._text_edit = QTextEdit()
        self._text_edit.setPlaceholderText("Text zum Vorlesen eingeben…")
        layout.addWidget(self._text_edit, 1)

        provider_row = QHBoxLayout()
        provider_row.setSpacing(6)
        provider_row.addWidget(QLabel("Anbieter:"))
        self._provider_combo = QComboBox()
        self._provider_combo.addItem("Piper lokal", "piper")
        self._provider_combo.addItem("OpenAI Cloud", "openai")
        self._provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_row.addWidget(self._provider_combo, 1)
        layout.addLayout(provider_row)

        voice_row = QHBoxLayout()
        voice_row.setSpacing(6)
        voice_row.addWidget(QLabel("Stimme:"))
        self._voice_combo = QComboBox()
        self._voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        voice_row.addWidget(self._voice_combo, 1)
        layout.addLayout(voice_row)

        model_row = QHBoxLayout()
        model_row.setSpacing(6)
        model_row.addWidget(QLabel("Modell:"))
        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText(OPENAI_TTS_MODEL_DEFAULT)
        self._model_edit.editingFinished.connect(self._on_model_changed)
        model_row.addWidget(self._model_edit, 1)
        layout.addLayout(model_row)

        speed_row = QHBoxLayout()
        speed_row.setSpacing(6)
        speed_row.addWidget(QLabel("Tempo:"))
        self._speed_combo = QComboBox()
        self._speed_combo.addItem("Sehr Schnell", 0.6)
        self._speed_combo.addItem("Schnell", 0.8)
        self._speed_combo.addItem("Normal", 1.0)
        self._speed_combo.addItem("Langsam", 1.25)
        self._speed_combo.addItem("Sehr Langsam", 1.5)
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

        self._btn_close = QPushButton("Schließen")
        self._btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self._btn_close)

        self._btn_replay = QPushButton("🔁 Nochmal")
        self._btn_replay.clicked.connect(self._on_replay_clicked)
        self._btn_replay.setEnabled(False)
        btn_row.addWidget(self._btn_replay)

        self._btn_pause = QPushButton("Pause")
        self._btn_pause.clicked.connect(self._on_pause_clicked)
        self._btn_pause.setEnabled(False)
        btn_row.addWidget(self._btn_pause)

        self._btn_speak = QPushButton("Vorlesen")
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
                self._voice_combo.addItem("(keine Stimmen gefunden)")
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
                self._status_label.setText("OpenAI Cloud-TTS bereit.")
                self._status_label.setStyleSheet("color: #4caf50;")
            else:
                self._status_label.setText(OPENAI_TTS_INSTALL_HINT)
                self._status_label.setStyleSheet("color: #f44336;")
        else:
            if self._piper_path:
                self._status_label.setText("Piper bereit.")
                self._status_label.setStyleSheet("color: #4caf50;")
            else:
                self._status_label.setText(PIPER_INSTALL_HINT)
                self._status_label.setStyleSheet("color: #f44336;")
        self._update_speak_button_state()

    def _update_speak_button_state(self) -> None:
        provider = self._current_provider()
        if provider == "openai":
            self._btn_speak.setEnabled(CloudTtsService(self._config).is_available() or self._cloud_is_running())
        else:
            self._btn_speak.setEnabled(bool(self._piper_path) or self._cloud_is_running())

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

    def _cloud_is_running(self) -> bool:
        return self._cloud_thread is not None and self._cloud_thread.isRunning()

    def _ensure_openai_consent(self) -> bool:
        """Einmalige Datenschutz-Bestaetigung fuer Cloud-TTS. True, wenn erteilt."""
        if self._config.tts_openai_consent:
            return True
        answer = QMessageBox.question(
            self,
            "OpenAI Cloud-TTS aktivieren?",
            OPENAI_TTS_CONSENT_TEXT,
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
        for proc in (self._piper_proc, self._aplay_proc):
            if proc is not None and proc.state() != QProcess.ProcessState.NotRunning:
                return True
        return self._cloud_is_running()

    @pyqtSlot()
    def _on_speak_clicked(self) -> None:
        if self._is_speaking():
            self._stop_tts()
            return
        self._start_tts()

    @pyqtSlot()
    def _on_replay_clicked(self) -> None:
        if not self._last_tts_text:
            return
        if self._is_speaking():
            self._stop_tts()
        self._start_tts(text=self._last_tts_text)

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
                self._btn_pause.setText("Pause")
                self._status_label.setText("Wiedergabe…")
            else:
                os.kill(pid, signal.SIGSTOP)
                self._is_paused = True
                self._btn_pause.setText("Fortsetzen")
                self._status_label.setText("Pausiert")
        except OSError:
            pass

    def _start_tts(self, text: Optional[str] = None) -> None:
        if text is None:
            text = self._current_tts_text()
        if not text:
            self._status_label.setText("Kein Text.")
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
            self._status_label.setText(PIPER_INSTALL_HINT)
            self._status_label.setStyleSheet("color: #f44336;")
            return

        model_path = self._current_voice()
        if not model_path:
            self._status_label.setText("Keine Stimme in ~/.local/share/piper-voices gefunden.")
            self._status_label.setStyleSheet("color: #f44336;")
            return

        proc = QProcess(self)
        proc.setProgram(self._piper_path)
        proc.setArguments([
            "--model", model_path,
            "--length_scale", str(float(self._config.tts_speed)),
            "--output_file", TTS_WAV,
        ])
        proc.finished.connect(self._on_piper_finished)
        proc.errorOccurred.connect(self._on_tts_error)
        self._piper_proc = proc

        self._status_label.setText("Synthese…")
        self._status_label.setStyleSheet("")
        self._btn_speak.setText("Stopp")
        self._update_speak_button_state()

        proc.start()
        proc.write(text.encode("utf-8"))
        proc.closeWriteChannel()

    def _start_cloud_tts(self, text: str) -> None:
        if not self._config.tts_openai_consent:
            self._status_label.setText("OpenAI Cloud-TTS wurde nicht bestaetigt.")
            self._status_label.setStyleSheet("color: #f44336;")
            self._update_speak_button_state()
            return
        service = CloudTtsService(self._config)
        if not service.is_available():
            self._status_label.setText(OPENAI_TTS_INSTALL_HINT)
            self._status_label.setStyleSheet("color: #f44336;")
            self._update_speak_button_state()
            return

        thread = QThread(self)
        worker = _CloudTtsWorker(service, text, TTS_WAV)
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

        self._status_label.setText("Cloud-Synthese…")
        self._status_label.setStyleSheet("")
        self._btn_speak.setText("Stopp")
        self._btn_pause.setEnabled(False)
        thread.start()
        self._update_speak_button_state()

    def _stop_tts(self) -> None:
        for attr in ("_piper_proc", "_aplay_proc"):
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

        self._btn_speak.setText("Vorlesen")
        self._btn_pause.setEnabled(False)
        self._is_paused = False
        self._btn_pause.setText("Pause")
        self._status_label.setText("Abgebrochen.")
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
        self._status_label.setText("Wiedergabe…")
        program, args = _playback_command(wav_path)
        aplay = QProcess(self)
        aplay.setProgram(program)
        aplay.setArguments(args)
        aplay.finished.connect(self._on_aplay_finished)
        aplay.errorOccurred.connect(self._on_tts_error)
        self._aplay_proc = aplay
        self._is_paused = False
        self._btn_pause.setText("Pause")
        self._btn_pause.setEnabled(True)
        self._btn_speak.setText("Stopp")
        aplay.start()

    @pyqtSlot(str)
    def _on_cloud_error(self, message: str) -> None:
        self._cleanup_cloud_state()
        self._status_label.setText(f"Fehler: {message}")
        self._status_label.setStyleSheet("color: #f44336;")
        self._btn_speak.setText("Vorlesen")
        self._btn_pause.setEnabled(False)
        self._is_paused = False
        self._btn_pause.setText("Pause")
        self._update_speak_button_state()
        QTimer.singleShot(2500, self._clear_status)

    def _on_cloud_thread_finished(self) -> None:
        self._cleanup_cloud_state()
        self._update_speak_button_state()

    @pyqtSlot(int, QProcess.ExitStatus)
    def _on_piper_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        proc = self._piper_proc
        self._piper_proc = None

        if exit_status != QProcess.ExitStatus.NormalExit or exit_code != 0:
            stderr = ""
            if proc is not None:
                stderr = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()
                proc.deleteLater()
            msg = stderr or f"Exit {exit_code}"
            self._status_label.setText(f"Fehler: {msg}")
            self._status_label.setStyleSheet("color: #f44336;")
            self._btn_speak.setText("Vorlesen")
            self._update_speak_button_state()
            QTimer.singleShot(2500, self._clear_status)
            return
        if proc is not None:
            proc.deleteLater()

        self._status_label.setText("Wiedergabe…")
        program, args = _playback_command(TTS_WAV)
        aplay = QProcess(self)
        aplay.setProgram(program)
        aplay.setArguments(args)
        aplay.finished.connect(self._on_aplay_finished)
        aplay.errorOccurred.connect(self._on_tts_error)
        self._aplay_proc = aplay
        self._is_paused = False
        self._btn_pause.setText("Pause")
        self._btn_pause.setEnabled(True)
        aplay.start()

    @pyqtSlot(int, QProcess.ExitStatus)
    def _on_aplay_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        proc = self._aplay_proc
        self._aplay_proc = None
        self._btn_speak.setText("Vorlesen")
        self._btn_pause.setEnabled(False)
        self._is_paused = False
        self._btn_pause.setText("Pause")
        if exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            self._status_label.setText("Fertig.")
            self._status_label.setStyleSheet("color: #4caf50;")
        else:
            stderr = ""
            if proc is not None:
                stderr = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()
            msg = stderr or f"Exit {exit_code}"
            self._status_label.setText(f"Fehler: {msg}")
            self._status_label.setStyleSheet("color: #f44336;")
        if proc is not None:
            proc.deleteLater()
        self._update_speak_button_state()
        QTimer.singleShot(2500, self._clear_status)

    @pyqtSlot(QProcess.ProcessError)
    def _on_tts_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._status_label.setText(PIPER_INSTALL_HINT if self._current_provider() == "piper" else OPENAI_TTS_INSTALL_HINT)
        else:
            self._status_label.setText(f"Fehler: {error.name}")
        self._status_label.setStyleSheet("color: #f44336;")
        self._btn_speak.setText("Vorlesen")
        self._btn_pause.setEnabled(False)
        self._is_paused = False
        self._btn_pause.setText("Pause")
        for attr in ("_piper_proc", "_aplay_proc"):
            proc = getattr(self, attr, None)
            if proc is not None:
                proc.deleteLater()
                setattr(self, attr, None)
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

"""Vorlese-Fenster (Text-to-Speech) auf Basis von Piper TTS.

Portiert aus whisper-dictation app/gui/tts_window.py, angepasst an die
Blitztext-Config (Config-Objekt statt Modul-Config).

Piper ist eine optionale Abhaengigkeit. Fehlt es, wird das Fenster mit einem
Installationshinweis angezeigt und die Vorlese-Funktion deaktiviert.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QProcess, QTimer, pyqtSlot
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

PIPER_VENV_PATH = str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "piper")
VOICES_DIR = Path.home() / ".local" / "share" / "piper-voices"
TTS_WAV = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir()),
    "blitztext-tts.wav",
)
PIPER_INSTALL_HINT = (
    "Piper nicht gefunden. Installieren: pip install piper-tts und Stimmen nach "
    "~/.local/share/piper-voices legen."
)


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


def _playback_command(wav_path: str) -> tuple[str, list[str]]:
    """paplay (PipeWire-nativ) vor aplay bevorzugen, um dmix-Konflikte zu meiden."""
    if shutil.which("paplay"):
        return "paplay", [wav_path]
    return "aplay", ["-D", "pipewire", wav_path]


class TtsWindow(QDialog):
    """Text -> Piper TTS. Non-blocking via QProcess, mit Abbruch + Stimmenwahl."""

    def __init__(self, config, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Vorlesen")
        self.resize(380, 280)
        self._piper_proc: Optional[QProcess] = None
        self._aplay_proc: Optional[QProcess] = None
        self._piper_path = _find_piper()
        self._last_tts_text = ""
        self._is_paused = False
        self._setup_ui()
        self._populate_voices()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        self._text_edit = QTextEdit()
        self._text_edit.setPlaceholderText("Text zum Vorlesen eingeben…")
        layout.addWidget(self._text_edit, 1)

        voice_row = QHBoxLayout()
        voice_row.setSpacing(6)
        voice_row.addWidget(QLabel("Stimme:"))
        self._voice_combo = QComboBox()
        self._voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        voice_row.addWidget(self._voice_combo, 1)

        voice_row.addWidget(QLabel("Tempo:"))
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
        voice_row.addWidget(self._speed_combo)

        layout.addLayout(voice_row)

        self._status_label = QLabel("")
        layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._btn_close = QPushButton("Schließen")
        self._btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self._btn_close)

        self._btn_replay = QPushButton("\U0001f501 Nochmal")
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

    def set_text(self, text: str) -> None:
        self._text_edit.setPlainText(text)

    def _populate_voices(self) -> None:
        if not self._piper_path:
            self._voice_combo.setEnabled(False)
            self._btn_speak.setEnabled(False)
            self._status_label.setText(PIPER_INSTALL_HINT)
            self._status_label.setStyleSheet("color: #f44336;")
            return

        voices = list_voices()
        self._voice_combo.blockSignals(True)
        self._voice_combo.clear()
        if not voices:
            self._voice_combo.addItem("(keine Stimmen gefunden)")
            self._voice_combo.setEnabled(False)
            self._btn_speak.setEnabled(False)
            self._status_label.setText(
                "Keine Stimmen in ~/.local/share/piper-voices gefunden."
            )
            self._status_label.setStyleSheet("color: #f44336;")
            self._voice_combo.blockSignals(False)
            return

        for label, path in voices:
            self._voice_combo.addItem(label, userData=path)

        saved_voice = str(self._config.tts_voice or "")
        selected = self._voice_combo.findData(saved_voice) if saved_voice else -1
        self._voice_combo.setCurrentIndex(selected if selected >= 0 else 0)
        self._voice_combo.blockSignals(False)

    @pyqtSlot(int)
    def _on_voice_changed(self, _idx: int) -> None:
        voice = self._voice_combo.currentData()
        if not isinstance(voice, str) or not voice:
            return
        if self._config.tts_voice == voice:
            return
        try:
            self._config.tts_voice = voice
            self._config.save()
        except Exception:
            pass

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

    def _current_voice(self) -> str:
        voice = self._voice_combo.currentData()
        if isinstance(voice, str) and voice:
            return voice
        voices = list_voices()
        return voices[0][1] if voices else ""

    def _is_speaking(self) -> bool:
        for proc in (self._piper_proc, self._aplay_proc):
            if proc is not None and proc.state() != QProcess.ProcessState.NotRunning:
                return True
        return False

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
            text = self._text_edit.toPlainText().strip()
        if not text:
            self._status_label.setText("Kein Text.")
            self._status_label.setStyleSheet("color: #f44336;")
            return
        self._last_tts_text = text
        self._btn_replay.setEnabled(True)
        if not self._piper_path:
            return

        model_path = self._current_voice()
        if not model_path:
            return

        speed = float(self._config.tts_speed)

        proc = QProcess(self)
        proc.setProgram(self._piper_path)
        proc.setArguments([
            "--model", model_path,
            "--length_scale", str(speed),
            "--output_file", TTS_WAV,
        ])
        proc.finished.connect(self._on_piper_finished)
        proc.errorOccurred.connect(self._on_tts_error)
        self._piper_proc = proc

        self._status_label.setText("Synthese…")
        self._status_label.setStyleSheet("")
        self._btn_speak.setText("Stopp")

        proc.start()
        proc.write(text.encode("utf-8"))
        proc.closeWriteChannel()

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
        self._btn_speak.setText("Vorlesen")
        self._btn_pause.setEnabled(False)
        self._is_paused = False
        self._btn_pause.setText("Pause")
        self._status_label.setText("Abgebrochen.")
        self._status_label.setStyleSheet("color: #ff9800;")
        QTimer.singleShot(2000, self._clear_status)

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
        QTimer.singleShot(2500, self._clear_status)

    @pyqtSlot(QProcess.ProcessError)
    def _on_tts_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self._status_label.setText(PIPER_INSTALL_HINT)
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

    def _clear_status(self) -> None:
        if not self._is_speaking():
            self._status_label.setText("")
            self._status_label.setStyleSheet("")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._is_speaking():
            self._stop_tts()
        super().closeEvent(event)

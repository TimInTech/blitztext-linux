"""AudioRecorder for BlitztextLinux.

Startet und stoppt Audioaufnahmen via parec (PulseAudio/PipeWire).
Extrahiert aus whisper-dictation scripts/dictate_toggle.py v0.2.19.

Design:
- Synchron (kein Thread): der aufrufende Thread blockiert nicht,
  parec laeuft als Hintergrundprozess.
- Stale-PID-Schutz: abgestuerzte parec-Prozesse werden erkannt
  und der PID-File wird bereinigt, bevor der naechste Start versucht wird.
- XDG_RUNTIME_DIR ist Pflicht (kein /tmp-Fallback, sicherheitsrelevant).
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("blitztext.audio_recorder")

# Aufnahme-Parameter (identisch zu whisper-dictation)
_RATE = 16000
_CHANNELS = 1
_LATENCY_MS = 100


class AudioRecorderError(Exception):
    """Raised when recording cannot be started or stopped cleanly."""


class AudioRecorder:
    """Verwaltet einen parec-Hintergrundprozess pro Aufnahme-Session.

    Typischer Ablauf:
        recorder = AudioRecorder()
        wav_path = recorder.start(device="@DEFAULT_SOURCE@")
        # ... warten (Hold-Modus: KEY_UP / Toggle-Modus: zweiter Hotkey-Press)
        wav_path = recorder.stop()  # gibt den Pfad zur WAV-Datei zurueck
    """

    def __init__(self, runtime_dir: Optional[Path] = None) -> None:
        """
        Args:
            runtime_dir: Pfad fuer PID- und WAV-Dateien.
                         Standard: $XDG_RUNTIME_DIR (Pflicht).
        """
        if runtime_dir is not None:
            self._runtime_dir = runtime_dir
        else:
            rt = os.environ.get("XDG_RUNTIME_DIR", "")
            if not rt or not Path(rt).is_dir():
                raise AudioRecorderError(
                    "XDG_RUNTIME_DIR ist nicht gesetzt oder existiert nicht. "
                    "AudioRecorder kann nicht initialisiert werden."
                )
            self._runtime_dir = Path(rt)

        user = os.environ.get("USER", "user")
        self._pid_file = self._runtime_dir / f"blitztext-linux-{user}.pid"
        self._wav_file = self._runtime_dir / f"blitztext-linux-{user}.wav"
        self._parec_err = self._runtime_dir / f"blitztext-linux-{user}.parec.err"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_recording(self) -> bool:
        """True, wenn ein parec-Prozess aktiv laeuft (PID-File existiert und Prozess lebt)."""
        return self._live_pid() is not None

    def start_recording(self, device: str = "@DEFAULT_SOURCE@") -> Path:
        return self.start(device)

    def stop_recording(self) -> Optional[Path]:
        return self.stop()

    def discard_recording(self) -> None:
        self.discard()

    def start(self, device: str = "@DEFAULT_SOURCE@") -> Path:
        """Startet eine neue Aufnahme.

        Args:
            device: PulseAudio/PipeWire Source-Name.
                    '@DEFAULT_SOURCE@' fuer das Standard-Mikrofon.

        Returns:
            Pfad zur WAV-Datei (wird waehrend der Aufnahme beschrieben).

        Raises:
            AudioRecorderError: Wenn parec nicht gefunden, PipeWire nicht
                                 erreichbar, Geraet unbekannt oder parec
                                 sofort abstuerzt.
        """
        if shutil.which("parec") is None:
            raise AudioRecorderError(
                "parec nicht gefunden. Bitte installieren: sudo apt install pulseaudio-utils"
            )

        # Stale-PID-Schutz (aus whisper-dictation v0.2.19)
        self._cleanup_stale_pid()

        if self._pid_file.is_file():
            raise AudioRecorderError(
                "Aufnahme laeuft bereits (PID-File vorhanden). Zuerst stop() aufrufen."
            )

        if not self._pipewire_available():
            raise AudioRecorderError("PulseAudio/PipeWire nicht erreichbar (pactl info fehlgeschlagen).")

        if not self._device_exists(device):
            raise AudioRecorderError(f"Mikrofon nicht gefunden: {device!r}")

        self._parec_err.unlink(missing_ok=True)
        err_fh = open(self._parec_err, "wb")
        try:
            proc = subprocess.Popen(
                [
                    "parec",
                    f"--device={device}",
                    "--file-format=wav",
                    f"--rate={_RATE}",
                    f"--channels={_CHANNELS}",
                    f"--latency-msec={_LATENCY_MS}",
                    str(self._wav_file),
                ],
                stdout=subprocess.DEVNULL,
                stderr=err_fh,
            )
        finally:
            err_fh.close()

        self._pid_file.write_text(f"{proc.pid}\n")

        # Kurz warten und sicherstellen, dass parec nicht sofort abgestuerzt ist
        time.sleep(0.2)
        if proc.poll() is not None:
            self._pid_file.unlink(missing_ok=True)
            self._wav_file.unlink(missing_ok=True)
            detail = self._read_parec_err()
            msg = f"parec sofort abgestuerzt: {detail}" if detail else "parec sofort abgestuerzt."
            raise AudioRecorderError(msg)

        logger.debug("Aufnahme gestartet: PID=%d device=%s", proc.pid, device)
        return self._wav_file

    def stop(self) -> Optional[Path]:
        """Stoppt die laufende Aufnahme.

        Returns:
            Pfad zur WAV-Datei wenn Audio vorhanden, sonst None.

        Raises:
            AudioRecorderError: Wenn keine Aufnahme lief.
        """
        self._cleanup_stale_pid()

        if not self._pid_file.is_file():
            raise AudioRecorderError("stop() aufgerufen, obwohl keine Aufnahme laeuft.")

        pid = self._read_pid()
        self._pid_file.unlink(missing_ok=True)

        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.4)  # parec Zeit geben, WAV-Header abzuschliessen
            except (ProcessLookupError, PermissionError, OSError) as exc:
                logger.debug("SIGTERM fehlgeschlagen (PID=%d): %s", pid, exc)

        if not self._wav_file.is_file() or self._wav_file.stat().st_size == 0:
            detail = self._read_parec_err()
            self._wav_file.unlink(missing_ok=True)
            if detail:
                logger.warning("Kein Audio aufgezeichnet: %s", detail)
            else:
                logger.warning("Kein Audio aufgezeichnet (leere WAV-Datei).")
            return None

        logger.debug("Aufnahme gestoppt: %s (%d Bytes)", self._wav_file, self._wav_file.stat().st_size)
        return self._wav_file

    def discard(self) -> None:
        """Bricht die laufende Aufnahme ab, ohne zu transkribieren.
        WAV-Datei wird geloescht. Kein Fehler wenn keine Aufnahme lief.
        """
        pid = self._live_pid()
        self._pid_file.unlink(missing_ok=True)
        if pid is not None:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        self._wav_file.unlink(missing_ok=True)
        logger.debug("Aufnahme verworfen.")

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    def _live_pid(self) -> Optional[int]:
        """Gibt PID zurueck wenn Prozess lebt, sonst None. Bereinigt Stale-PID."""
        if not self._pid_file.is_file():
            return None
        pid = self._read_pid()
        if pid is None:
            self._pid_file.unlink(missing_ok=True)
            return None
        try:
            os.kill(pid, 0)
            return pid
        except OSError:
            self._pid_file.unlink(missing_ok=True)
            return None

    def _cleanup_stale_pid(self) -> None:
        """Entfernt PID-File wenn Prozess nicht mehr laeuft (Stale-PID-Schutz)."""
        if not self._pid_file.is_file():
            return
        pid = self._read_pid()
        if pid is None:
            self._pid_file.unlink(missing_ok=True)
            return
        try:
            os.kill(pid, 0)  # Signal 0 = nur Existenz-Check, kein Kill
        except OSError:
            logger.debug("Stale PID %d bereinigt.", pid)
            self._pid_file.unlink(missing_ok=True)

    def _read_pid(self) -> Optional[int]:
        try:
            return int(self._pid_file.read_text().strip())
        except (OSError, ValueError):
            return None

    def _read_parec_err(self) -> str:
        try:
            if self._parec_err.is_file() and self._parec_err.stat().st_size > 0:
                text = self._parec_err.read_text(errors="replace").strip()
                first = text.splitlines()[0] if text else ""
                return (first[:157] + "...") if len(first) > 160 else first
        except OSError:
            pass
        return ""

    @staticmethod
    def _pipewire_available() -> bool:
        try:
            result = subprocess.run(
                ["pactl", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def _device_exists(device: str) -> bool:
        if device == "@DEFAULT_SOURCE@":
            return True
        try:
            result = subprocess.run(
                ["pactl", "list", "sources", "short"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            for line in result.stdout.splitlines():
                parts = line.split("\t")
                if len(parts) >= 2 and parts[1] == device:
                    return True
            return False
        except Exception:
            return False

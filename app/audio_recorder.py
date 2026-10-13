"""AudioRecorder for BlitztextLinux.

Starts and stops audio recordings via parec (PulseAudio/PipeWire).

Design:
- Synchron (kein Thread): der aufrufende Thread blockiert nicht,
  parec laeuft als Hintergrundprozess.
- Only the child started by this instance can be controlled, using a pidfd.
  PID files are untrusted status markers, never signal targets.
- XDG_RUNTIME_DIR ist Pflicht (kein /tmp-Fallback, sicherheitsrelevant).
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("blitztext.audio_recorder")

# Recording parameters for Whisper-compatible 16 kHz mono WAV input.
_RATE = 16000
_CHANNELS = 1
_LATENCY_MS = 100
_STOP_TIMEOUT = 2.0
# The child cannot capture audio until the parent has pinned its identity. EOF
# aborts startup without a signal; exec preserves the PID and its pidfd binding.
_START_GATE = (
    "import os, sys\n"
    "if sys.stdin.buffer.read(1) == b'1':\n"
    "    os.execvp(sys.argv[1], sys.argv[1:])\n"
)


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
        self._process: Optional[subprocess.Popen] = None
        self._pidfd: Optional[int] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_recording(self) -> bool:
        """True only while this instance's recording child is alive."""
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

        # Stale PID guard for interrupted recording processes.
        self._cleanup_stale_pid()

        if self._process is not None:
            raise AudioRecorderError(
                "Aufnahme laeuft bereits. Zuerst stop() aufrufen."
            )

        if not self._pipewire_available():
            raise AudioRecorderError("PulseAudio/PipeWire nicht erreichbar (pactl info fehlgeschlagen).")

        if not self._device_exists(device):
            raise AudioRecorderError(f"Mikrofon nicht gefunden: {device!r}")

        # Fail before starting capture on kernels without safe process handles.
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise AudioRecorderError("Sichere Aufnahme-Prozessverwaltung benoetigt Linux pidfd-Unterstuetzung.")
        try:
            probe_fd = os.pidfd_open(os.getpid())
            os.close(probe_fd)
        except OSError as exc:
            raise AudioRecorderError("Linux pidfd-Unterstuetzung ist nicht verfuegbar.") from exc

        self._parec_err.unlink(missing_ok=True)
        err_fh = open(self._parec_err, "wb")
        try:
            proc = subprocess.Popen(
                [
                    sys.executable, "-I", "-S", "-c", _START_GATE,
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
                stdin=subprocess.PIPE,
            )
        except OSError as exc:
            raise AudioRecorderError(f"Aufnahme-Prozess konnte nicht gestartet werden: {exc}") from exc
        finally:
            err_fh.close()

        # This local Popen child has not been polled/reaped or exposed to another
        # caller yet. Its PID cannot be recycled before pidfd_open pins it.
        try:
            pidfd = os.pidfd_open(proc.pid)
        except OSError as exc:
            # EOF ends the gate without starting parec or trusting a numeric PID.
            self._process = proc
            proc.stdin.close()
            try:
                proc.wait(timeout=_STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                logger.warning("Aufnahme-Startbarriere ist noch nicht beendet (PID=%d).", proc.pid)
            else:
                self._release_process()
            raise AudioRecorderError(
                "Aufnahme-Prozess konnte nicht sicher vorbereitet werden; Aufnahme nicht gestartet."
            ) from exc
        self._process = proc
        self._pidfd = pidfd

        try:
            self._pid_file.write_text(f"{proc.pid}\n")
            # No shell interpolation; all parec arguments cross exec as argv.
            with proc.stdin:
                proc.stdin.write(b"1")
        except OSError as exc:
            if not proc.stdin.closed:
                proc.stdin.close()
            if self._stop_owned_process():
                self._wav_file.unlink(missing_ok=True)
            raise AudioRecorderError("Aufnahme-Prozess konnte nicht freigegeben werden.") from exc

        # Kurz warten und sicherstellen, dass parec nicht sofort abgestuerzt ist
        time.sleep(0.2)
        if proc.poll() is not None:
            self._release_process()
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
        if self._live_pid() is None:
            raise AudioRecorderError("stop() aufgerufen, obwohl keine Aufnahme laeuft.")

        if not self._stop_owned_process():
            raise AudioRecorderError("Aufnahme-Prozess konnte nicht sicher gestoppt werden.")

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
        if self._live_pid() is not None and not self._stop_owned_process():
            # Preserve the handle and files rather than pretending capture ended.
            logger.warning("Aufnahme konnte nicht sicher verworfen werden.")
            return
        self._wav_file.unlink(missing_ok=True)
        logger.debug("Aufnahme verworfen.")

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    def _live_pid(self) -> Optional[int]:
        """Return only the owned child PID; never trust or probe a PID file."""
        if self._process is not None and self._process.poll() is None:
            return self._process.pid
        self._release_process()
        return None

    def _cleanup_stale_pid(self) -> None:
        """Clean up markers without adopting or signalling unowned processes."""
        self._live_pid()

    def _release_process(self) -> None:
        """Release the identity handle only after the child has stopped."""
        if self._pidfd is not None:
            os.close(self._pidfd)
            self._pidfd = None
        self._process = None
        try:
            self._pid_file.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Aufnahme-PID-Marker konnte nicht entfernt werden: %s", exc)

    def _stop_owned_process(self) -> bool:
        """Signal the pinned child, even if its numeric PID is later recycled."""
        proc = self._process
        if proc is None:
            return True
        if self._pidfd is None:
            logger.warning("Kein verifizierter Prozess-Handle fuer Aufnahme-PID %d.", proc.pid)
            return False
        try:
            try:
                signal.pidfd_send_signal(self._pidfd, signal.SIGTERM)
            except ProcessLookupError:
                pass  # The pinned child exited before delivery; no PID fallback.
            try:
                proc.wait(timeout=_STOP_TIMEOUT)
            except subprocess.TimeoutExpired:
                try:
                    signal.pidfd_send_signal(self._pidfd, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=_STOP_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.warning("Aufnahme-Prozess konnte nicht gestoppt werden: %s", exc)
            return False
        self._release_process()
        return True

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

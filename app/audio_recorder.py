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
import stat
import subprocess
import sys
import tempfile
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
        rt = runtime_dir if runtime_dir is not None else os.environ.get("XDG_RUNTIME_DIR", "")
        if not rt:
            raise AudioRecorderError("XDG_RUNTIME_DIR ist nicht gesetzt.")
        self._runtime_dir = Path(rt)
        self._process: Optional[subprocess.Popen] = None
        self._pidfd: Optional[int] = None
        self._runtime_fd: int | None = None
        self._job_fd: int | None = None
        self._new_job()

    @staticmethod
    def _open_runtime(path: Path) -> int:
        """Walk an absolute path without following links, then check privacy.

        Parents must be owned by root or this effective UID and not writable by
        others. Root-owned sticky directories (e.g. /tmp in isolated tests) are
        safe parents: other users cannot rename our private child directory.
        """
        if not path.is_absolute() or ".." in path.parts:
            raise AudioRecorderError("Recorder-Runtime muss ein absoluter Pfad ohne '..' sein.")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        fd = os.open("/", flags)
        try:
            for component in path.parts[1:]:
                parent = os.fstat(fd)
                sticky_root = parent.st_uid == 0 and bool(parent.st_mode & stat.S_ISVTX)
                if parent.st_uid not in (0, os.geteuid()) or (parent.st_mode & 0o022 and not sticky_root):
                    raise AudioRecorderError("Unsicheres Elternverzeichnis der Recorder-Runtime.")
                child = os.open(component, flags, dir_fd=fd)
                os.close(fd)
                fd = child
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise AudioRecorderError("Recorder-Runtime muss dem Benutzer gehoeren und Rechte 0700 haben.")
            return fd
        except BaseException:
            os.close(fd)
            raise

    def _new_job(self) -> None:
        """Create a unique private job through a verified directory handle."""
        runtime_fd = None
        job_fd = None
        created = None
        try:
            runtime_fd = self._open_runtime(self._runtime_dir)
            # The procfs path pins creation to the checked inode, including when
            # a pathname is renamed during startup. mkdtemp uses atomic mkdir.
            created = Path(tempfile.mkdtemp(prefix="blitztext-recording-", dir=f"/proc/self/fd/{runtime_fd}"))
            job_fd = os.open(created.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=runtime_fd)
            os.fchmod(job_fd, 0o700)
        except OSError as exc:
            if job_fd is not None:
                os.close(job_fd)
            if runtime_fd is not None:
                try:
                    if created is not None:
                        os.rmdir(created.name, dir_fd=runtime_fd)
                finally:
                    os.close(runtime_fd)
            raise AudioRecorderError("Sichere Recorder-Runtime konnte nicht erstellt werden.") from exc
        except BaseException:
            if runtime_fd is not None:
                os.close(runtime_fd)
            raise
        self._runtime_fd = runtime_fd
        self._job_fd = job_fd
        self._job_name = created.name
        self._job_dir = self._runtime_dir / self._job_name
        self._pid_file = self._job_dir / "recorder.pid"
        self._wav_file = self._job_dir / "recording.wav"
        self._parec_err = self._job_dir / "parec.err"

    def _check_job(self) -> None:
        """Recheck permissions and pathname identity before handing out paths."""
        try:
            fd = self._open_runtime(self._runtime_dir)
            try:
                current = os.fstat(fd)
                pinned = os.fstat(self._runtime_fd)
                if (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino):
                    raise AudioRecorderError("Recorder-Runtime wurde ersetzt.")
                job = os.stat(self._job_name, dir_fd=fd, follow_symlinks=False)
                pinned_job = os.fstat(self._job_fd)
                if (
                    (job.st_dev, job.st_ino) != (pinned_job.st_dev, pinned_job.st_ino)
                    or not stat.S_ISDIR(job.st_mode)
                    or job.st_uid != os.geteuid()
                    or stat.S_IMODE(job.st_mode) != 0o700
                ):
                    raise AudioRecorderError("Recorder-Jobverzeichnis ist unsicher oder wurde ersetzt.")
            finally:
                os.close(fd)
        except OSError as exc:
            raise AudioRecorderError("Recorder-Runtime konnte nicht sicher geprueft werden.") from exc

    def _create_file(self, name: str):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self._job_fd)
        try:
            # Also retain 0600 under a restrictive caller umask.
            os.fchmod(fd, 0o600)
            return os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            raise

    def _unlink_file(self, name: str) -> None:
        if self._job_fd is None:
            return
        try:
            os.unlink(name, dir_fd=self._job_fd)
        except FileNotFoundError:
            pass

    def _finish_job(self, *, keep_wav: bool = False) -> None:
        """Never remove a successful WAV: its consumer owns that lifecycle."""
        if self._job_fd is None:
            return
        try:
            for name in ("recorder.pid", "parec.err") + (() if keep_wav else ("recording.wav",)):
                self._unlink_file(name)
            if not keep_wav:
                entry = os.stat(self._job_name, dir_fd=self._runtime_fd, follow_symlinks=False)
                pinned = os.fstat(self._job_fd)
                if (entry.st_dev, entry.st_ino) == (pinned.st_dev, pinned.st_ino):
                    os.rmdir(self._job_name, dir_fd=self._runtime_fd)
        except OSError as exc:
            logger.warning("Recorder-Job konnte nicht vollstaendig entfernt werden: %s", exc)
        finally:
            self._close_job_handles()

    def _close_job_handles(self) -> None:
        for attr in ("_job_fd", "_runtime_fd"):
            fd = getattr(self, attr, None)
            if fd is not None:
                os.close(fd)
                setattr(self, attr, None)

    def __del__(self) -> None:
        # Successful stop has already detached the job, preserving its WAV.
        # Remove unused jobs, but never unlink files of a retained child.
        if getattr(self, "_job_fd", None) is not None and getattr(self, "_process", None) is None:
            self._finish_job()
        else:
            self._close_job_handles()

    @classmethod
    def cleanup_recording(cls, wav: Path) -> None:
        """Worker-only cleanup after transcription, independent of later jobs."""
        runtime_fd = cls._open_runtime(wav.parent.parent)
        job_fd = None
        try:
            if wav.name != "recording.wav" or not wav.parent.name.startswith("blitztext-recording-"):
                raise AudioRecorderError("Ungueltiger Recorder-Jobpfad.")
            job_fd = os.open(wav.parent.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=runtime_fd)
            info = os.fstat(job_fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise AudioRecorderError("Unsicheres Recorder-Jobverzeichnis.")
            for name in ("recording.wav", "recorder.pid", "parec.err"):
                try:
                    os.unlink(name, dir_fd=job_fd)
                except FileNotFoundError:
                    pass
            os.rmdir(wav.parent.name, dir_fd=runtime_fd)
        finally:
            if job_fd is not None:
                os.close(job_fd)
            os.close(runtime_fd)

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

        if self._job_fd is None:
            self._new_job()
        self._check_job()
        try:
            wav_fh = self._create_file("recording.wav")
            try:
                err_fh = self._create_file("parec.err")
            except BaseException:
                wav_fh.close()
                raise
        except OSError as exc:
            self._finish_job()
            raise AudioRecorderError("Recorder-Dateien konnten nicht sicher erstellt werden.") from exc
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
                    f"/proc/self/fd/{wav_fh.fileno()}",
                ],
                stdout=subprocess.DEVNULL,
                stderr=err_fh,
                stdin=subprocess.PIPE,
                pass_fds=(wav_fh.fileno(),),
            )
        except OSError as exc:
            self._finish_job()
            raise AudioRecorderError(f"Aufnahme-Prozess konnte nicht gestartet werden: {exc}") from exc
        finally:
            err_fh.close()
            wav_fh.close()

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
                self._finish_job()
            raise AudioRecorderError(
                "Aufnahme-Prozess konnte nicht sicher vorbereitet werden; Aufnahme nicht gestartet."
            ) from exc
        self._process = proc
        self._pidfd = pidfd

        try:
            with self._create_file("recorder.pid") as marker:
                marker.write(f"{proc.pid}\n".encode("ascii"))
            # No shell interpolation; all parec arguments cross exec as argv.
            with proc.stdin:
                proc.stdin.write(b"1")
        except OSError as exc:
            if not proc.stdin.closed:
                proc.stdin.close()
            if self._stop_owned_process():
                self._finish_job()
            raise AudioRecorderError("Aufnahme-Prozess konnte nicht freigegeben werden.") from exc

        # Kurz warten und sicherstellen, dass parec nicht sofort abgestuerzt ist
        time.sleep(0.2)
        if proc.poll() is not None:
            self._release_process()
            detail = self._read_parec_err()
            self._finish_job()
            msg = f"parec sofort abgestuerzt: {detail}" if detail else "parec sofort abgestuerzt."
            raise AudioRecorderError(msg)

        try:
            self._check_job()
        except AudioRecorderError:
            if self._stop_owned_process():
                self._finish_job()
            raise

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

        try:
            self._check_job()
            info = os.stat("recording.wav", dir_fd=self._job_fd, follow_symlinks=False)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
            ):
                raise AudioRecorderError("Unsichere WAV-Datei.")
        except (OSError, AudioRecorderError) as exc:
            self._finish_job()
            raise AudioRecorderError("WAV-Datei konnte nicht sicher geprueft werden.") from exc
        if info.st_size == 0:
            detail = self._read_parec_err()
            self._finish_job()
            logger.warning("Kein Audio aufgezeichnet: %s", detail or "leere WAV-Datei")
            return None

        logger.debug("Aufnahme gestoppt: %s (%d Bytes)", self._job_name, info.st_size)
        self._finish_job(keep_wav=True)
        return self._wav_file

    def discard(self) -> None:
        """Bricht die laufende Aufnahme ab, ohne zu transkribieren.
        WAV-Datei wird geloescht. Kein Fehler wenn keine Aufnahme lief.
        """
        if self._live_pid() is not None and not self._stop_owned_process():
            # Preserve the handle and files rather than pretending capture ended.
            logger.warning("Aufnahme konnte nicht sicher verworfen werden.")
            return
        self._finish_job()
        logger.debug("Aufnahme verworfen.")

    # ------------------------------------------------------------------
    # Interne Hilfsmethoden
    # ------------------------------------------------------------------

    def _live_pid(self) -> Optional[int]:
        """Return only the owned child PID; never trust or probe a PID file."""
        if self._process is not None and self._process.poll() is None:
            return self._process.pid
        had_process = self._process is not None
        self._release_process()
        if had_process:
            self._finish_job()
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
            self._unlink_file("recorder.pid")
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
        if self._job_fd is None:
            return ""
        try:
            fd = os.open("parec.err", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=self._job_fd)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
                    return ""
                text = stream.read(4096).decode(errors="replace").strip()
                first = text.splitlines()[0] if text else ""
                return (first[:157] + "...") if len(first) > 160 else first
        except OSError:
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

"""Recorder ownership regressions; no microphone or foreign process signals."""
from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.audio_recorder import AudioRecorder, AudioRecorderError


@pytest.mark.parametrize("pid_text", ["-1", "-123", "0", "1", str(os.getpid()), "999999999", "bad", "", "9" * 100])
@pytest.mark.parametrize("operation", ["is_recording", "stop", "discard", "_cleanup_stale_pid"])
def test_pid_file_never_authorizes_a_signal(tmp_path: Path, pid_text: str, operation: str):
    recorder = AudioRecorder(tmp_path)
    recorder._pid_file.write_text(pid_text)

    # Even signal 0 must not be sent to an unowned PID. Mock the unsafe old
    # boundary so the regression is safe when run against the vulnerable code.
    with patch("app.audio_recorder.os.kill") as kill, \
            patch("app.audio_recorder.signal.pidfd_send_signal") as send, \
            patch("app.audio_recorder.time.sleep"):
        if operation == "stop":
            with pytest.raises(AudioRecorderError):
                recorder.stop()
        else:
            result = getattr(recorder, operation)()
            if operation == "is_recording":
                assert result is False
        kill.assert_not_called()
        send.assert_not_called()
    assert not recorder._pid_file.exists()


@pytest.fixture
def recording(tmp_path: Path, monkeypatch):
    """Exercise real Popen/pidfd with a disposable, microphone-free parec."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "parec"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os, signal, sys, time\n"
        "from pathlib import Path\n"
        "wav = Path(sys.argv[-1])\n"
        "mode = os.environ.get('BT_TEST_PAREC_MODE', 'normal')\n"
        "if mode == 'crash':\n"
        "    sys.stderr.write('isolated recorder failure\\n')\n"
        "    sys.exit(7)\n"
        "def finish(*_):\n"
        "    wav.write_bytes(b'finished' if mode != 'empty' else b'')\n"
        "    sys.exit(0)\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN if mode == 'ignore' else finish)\n"
        "wav.write_bytes(b'recording' if mode != 'empty' else b'')\n"
        "while True: time.sleep(0.01)\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(AudioRecorder, "_pipewire_available", staticmethod(lambda: True))
    monkeypatch.setattr(AudioRecorder, "_device_exists", staticmethod(lambda _device: True))
    processes = []
    popen = subprocess.Popen
    pidfd_open = os.pidfd_open
    send_signal = signal.pidfd_send_signal

    def spawn(*args, **kwargs):
        proc = popen(*args, **kwargs)
        processes.append(proc)
        return proc

    def signal_test_child(fd, sig, *args):
        # Refuse foreign targets even if a regression accidentally adopts a PID
        # file. A dead pidfd reports -1 and can only raise ESRCH, never redirect.
        info = Path(f"/proc/self/fdinfo/{fd}").read_text()
        target = next(int(line.split()[1]) for line in info.splitlines() if line.startswith("Pid:"))
        assert target == -1 or target in {proc.pid for proc in processes}, "refusing foreign signal target"
        return send_signal(fd, sig, *args)

    monkeypatch.setattr("app.audio_recorder.subprocess.Popen", spawn)
    monkeypatch.setattr("app.audio_recorder.signal.pidfd_send_signal", signal_test_child)
    recorder = AudioRecorder(tmp_path)
    yield recorder, processes
    # Clean up only children created by this fixture, using an identity-bound
    # descriptor even if a failing test left the recorder unable to stop them.
    for proc in processes:
        if proc.poll() is None:
            fd = pidfd_open(proc.pid)
            try:
                send_signal(fd, signal.SIGKILL)
                proc.wait(timeout=5)
            finally:
                os.close(fd)
    fd = getattr(recorder, "_pidfd", None)
    if fd is not None:
        os.close(fd)


def test_normal_stop_waits_for_owned_recording_and_closes_pidfd(recording):
    recorder, processes = recording
    wav = recorder.start()
    fd = recorder._pidfd
    assert recorder.is_recording()
    assert recorder.stop() == wav
    assert wav.read_bytes() == b"finished"
    assert processes[0].returncode == 0
    assert not recorder.is_recording()
    assert not recorder._pid_file.exists()
    with pytest.raises(OSError) as error:
        os.fstat(fd)
    assert error.value.errno == errno.EBADF


@pytest.mark.parametrize("pid_text", ["-1", "0", str(os.getpid()), "bad", None])
@pytest.mark.parametrize("operation", ["stop", "discard"])
def test_changed_or_missing_pid_file_cannot_redirect_owned_signal(recording, pid_text, operation):
    recorder, processes = recording
    wav = recorder.start()
    if pid_text is None:
        recorder._pid_file.unlink()
    else:
        recorder._pid_file.write_text(pid_text)
    with patch("app.audio_recorder.os.kill") as kill:
        getattr(recorder, operation)()
        kill.assert_not_called()
    assert processes[0].returncode == 0
    assert wav.exists() is (operation == "stop")
    assert not recorder._pid_file.exists()
    assert not recorder.is_recording()


def test_second_start_does_not_spawn_another_child(recording):
    recorder, processes = recording
    recorder.start()
    with pytest.raises(AudioRecorderError):
        recorder.start()
    assert len(processes) == 1
    recorder.discard()


def test_foreign_marker_does_not_block_new_owned_recording(recording):
    recorder, _ = recording
    recorder._pid_file.write_text(str(os.getpid()))
    with patch("app.audio_recorder.os.kill") as kill:
        recorder.start()
        recorder.discard()
        kill.assert_not_called()


def test_exited_child_is_not_signalled_again(recording):
    recorder, processes = recording
    recorder.start()
    signal.pidfd_send_signal(recorder._pidfd, signal.SIGTERM)
    processes[0].wait(timeout=5)
    with patch("app.audio_recorder.os.kill") as kill, patch("app.audio_recorder.signal.pidfd_send_signal") as send:
        recorder.discard()
        kill.assert_not_called()
        send.assert_not_called()
    assert not recorder.is_recording()
    assert not recorder._pid_file.exists()


def test_crashed_recording_reports_error_and_releases_identity(recording, monkeypatch):
    recorder, processes = recording
    monkeypatch.setenv("BT_TEST_PAREC_MODE", "crash")
    with pytest.raises(AudioRecorderError, match="isolated recorder failure"):
        recorder.start()
    assert processes[0].returncode == 7
    assert not recorder.is_recording()
    assert recorder._pidfd is None
    assert not recorder._pid_file.exists()
    assert not recorder._wav_file.exists()


def test_empty_recording_returns_none_after_stopping_owned_child(recording, monkeypatch):
    recorder, processes = recording
    monkeypatch.setenv("BT_TEST_PAREC_MODE", "empty")
    recorder.start()
    assert recorder.stop() is None
    assert processes[0].returncode == 0
    assert not recorder._wav_file.exists()


def test_unresponsive_child_is_killed_only_through_owned_pidfd(recording, monkeypatch):
    recorder, processes = recording
    monkeypatch.setenv("BT_TEST_PAREC_MODE", "ignore")
    recorder.start()
    with patch("app.audio_recorder.os.kill") as kill:
        recorder.discard()
        kill.assert_not_called()
    assert processes[0].returncode == -signal.SIGKILL
    assert not recorder.is_recording()


def test_unsupported_pidfd_prevents_spawning_recorder(recording):
    recorder, processes = recording
    with patch("app.audio_recorder.os.pidfd_open", side_effect=OSError(errno.ENOSYS, "unsupported")), patch("app.audio_recorder.os.kill") as kill:
        with pytest.raises(AudioRecorderError):
            recorder.start()
        kill.assert_not_called()
    assert processes == []


def test_spawn_failure_reports_recorder_error_without_retaining_identity(recording):
    recorder, processes = recording
    with patch("app.audio_recorder.subprocess.Popen", side_effect=FileNotFoundError("isolated spawn failure")):
        with pytest.raises(AudioRecorderError):
            recorder.start()
    assert processes == []
    assert not recorder.is_recording()
    assert recorder._pidfd is None
    assert not recorder._pid_file.exists()


def test_child_exit_between_check_and_delivery_cannot_redirect_signal(recording):
    recorder, processes = recording
    wav = recorder.start()
    send_signal = signal.pidfd_send_signal

    def exit_before_delivery(fd, sig):
        # Reap only this test's child after the recorder's liveness check.
        # The descriptor stays bound to the dead child, never a reused PID.
        send_signal(fd, signal.SIGTERM)
        processes[0].wait(timeout=5)
        return send_signal(fd, sig)

    with patch("app.audio_recorder.signal.pidfd_send_signal", side_effect=exit_before_delivery), patch("app.audio_recorder.os.kill") as kill:
        assert recorder.stop() == wav
        kill.assert_not_called()
    assert not recorder.is_recording()


def test_pid_marker_write_failure_stops_only_owned_child(recording, monkeypatch):
    recorder, processes = recording
    write_text = Path.write_text

    def fail_marker_write(path, *args, **kwargs):
        if path == recorder._pid_file:
            raise PermissionError("isolated marker failure")
        return write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_marker_write)
    with patch("app.audio_recorder.os.kill") as kill:
        with pytest.raises(AudioRecorderError):
            recorder.start()
        kill.assert_not_called()
    assert processes[0].returncode is not None
    assert not recorder.is_recording()


def test_failed_identity_acquisition_never_falls_back_to_numeric_pid(recording):
    recorder, processes = recording
    pidfd_open = os.pidfd_open

    def reject_child(pid, flags=0):
        if pid == os.getpid():
            return pidfd_open(pid, flags)
        raise PermissionError("isolated identity failure")

    with patch("app.audio_recorder.os.pidfd_open", side_effect=reject_child), patch("app.audio_recorder.os.kill") as kill:
        with pytest.raises(AudioRecorderError):
            recorder.start()
        assert processes[0].wait(timeout=2) == 0
        with pytest.raises(AudioRecorderError):
            recorder.stop()
        recorder.discard()
        kill.assert_not_called()
    assert not recorder.is_recording()
    assert not recorder._wav_file.exists()


def test_signal_failure_preserves_owned_process_for_retry(recording):
    recorder, processes = recording
    recorder.start()
    with patch("app.audio_recorder.signal.pidfd_send_signal", side_effect=PermissionError("denied")), patch("app.audio_recorder.os.kill") as kill:
        with pytest.raises(AudioRecorderError):
            recorder.stop()
        recorder.discard()
        kill.assert_not_called()
    assert processes[0].poll() is None
    assert recorder.is_recording()
    recorder.discard()
    assert not recorder.is_recording()


@pytest.mark.parametrize("operation,denied", [
    ("gui_discard", False), ("gui_discard", True),
    ("_stop_recording_and_process", True),
    ("quit_app", False), ("quit_app", True),
])
def test_application_preserves_state_until_recording_has_stopped(recording, operation, denied):
    from app.blitztext_linux import BlitztextApp

    recorder, processes = recording
    recorder.start()
    errors = []
    shutdown = []
    controller = SimpleNamespace(
        audio_recorder=recorder,
        state="RECORDING",
        current_workflow="isolated-workflow",
        _recording_routes_to_compose=True,
        _compose_voice_routing_enabled=lambda: True,
        show_tray_error=lambda *args: errors.append(args),
        stop_hotkey_worker=lambda: shutdown.append("hotkeys"),
        _tts_window=None, _history_panel=None, _compose_window=None, _main_window=None,
        tray_icon=SimpleNamespace(hide=lambda: shutdown.append("tray")),
        app=SimpleNamespace(quit=lambda: shutdown.append("quit")),
    )
    controller._set_state = lambda state, _reason: setattr(controller, "state", state)
    failure = patch("app.audio_recorder.signal.pidfd_send_signal", side_effect=PermissionError("denied")) if denied else nullcontext()
    with failure:
        getattr(BlitztextApp, operation)(controller)
    if denied:
        assert processes[0].poll() is None
        assert controller.state == "RECORDING"
        assert controller.current_workflow == "isolated-workflow"
        assert controller._recording_routes_to_compose is True
        assert errors
        assert shutdown == []
    else:
        assert processes[0].returncode == 0
        assert not errors
        if operation == "quit_app":
            assert shutdown == ["hotkeys", "tray", "quit"]
        else:
            assert controller.state == "IDLE"
            assert controller.current_workflow is None
            assert controller._recording_routes_to_compose is False


def test_marker_cleanup_failure_does_not_hide_successful_process_stop(recording, monkeypatch):
    recorder, processes = recording
    wav = recorder.start()
    fd = recorder._pidfd
    unlink = Path.unlink

    def deny_marker_unlink(path, *args, **kwargs):
        if path == recorder._pid_file:
            raise PermissionError("isolated cleanup failure")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny_marker_unlink)
    assert recorder.stop() == wav
    assert processes[0].returncode == 0
    assert not recorder.is_recording()
    assert recorder._pidfd is None
    with pytest.raises(OSError) as error:
        os.fstat(fd)
    assert error.value.errno == errno.EBADF

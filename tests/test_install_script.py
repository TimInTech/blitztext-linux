from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# NOTE: tests/conftest.py's autouse `_block_real_notifications` fixture patches
# `subprocess.run` process-wide (it patches the shared `subprocess` module via
# `app.notify.subprocess.run`). Resolving real tool paths must therefore use
# `shutil.which`, not `subprocess.run(["which", ...])`.
BASH = shutil.which("bash")


def _write_stub(path: Path, body: str) -> None:
    path.write_text(f"#!{BASH}\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _prepare_install_script(tmp_path: Path, repo_root: Path) -> tuple[Path, Path]:
    """Builds a fake repo + PATH so install.sh can run to completion without
    touching real system packages, sudo, or systemd state.

    Strategy: shadow only the specific external commands whose real-world
    invocation would be destructive or non-deterministic (dpkg-query,
    systemctl, pgrep, ydotool, sudo, pip) by prepending a stub bin directory
    to the inherited PATH. Everything else (grep, sed, id, python3, ...)
    keeps using the real inherited PATH, since those calls are read-only and
    their real behavior is safe and deterministic across Ubuntu/Debian hosts.
    """
    repo_dir = tmp_path / "repo"
    scripts_dir = repo_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script_path = scripts_dir / "install.sh"
    script_path.write_text((repo_root / "scripts" / "install.sh").read_text(encoding="utf-8"), encoding="utf-8")
    script_path.chmod(0o755)

    systemd_dir = repo_dir / "systemd"
    systemd_dir.mkdir(parents=True, exist_ok=True)
    (systemd_dir / "blitztext-linux.service").write_text(
        (repo_root / "systemd" / "blitztext-linux.service").read_text(encoding="utf-8"), encoding="utf-8"
    )

    venv_bin = repo_dir / ".venv" / "bin"
    venv_bin.mkdir(parents=True, exist_ok=True)
    _write_stub(venv_bin / "pip", "exit 0")

    stub_bin = tmp_path / "bin"
    stub_bin.mkdir(parents=True, exist_ok=True)

    _write_stub(stub_bin / "dpkg-query", 'printf "install ok installed\\n"\nexit 0')
    _write_stub(stub_bin / "ydotool", "exit 0")
    _write_stub(stub_bin / "pgrep", "exit 1")
    _write_stub(stub_bin / "sudo", 'exec "$@"')
    _write_stub(
        stub_bin / "systemctl",
        r"""
args="$*"
case "$args" in
  *"ydotool.service"*)
    exit 1
    ;;
  *"is-active --quiet blitztext-linux"*)
    [[ "${BT_TEST_APP_ACTIVE:-0}" == "1" ]] && exit 0 || exit 1
    ;;
  *"is-enabled --quiet blitztext-linux"*)
    [[ "${BT_TEST_APP_ENABLED:-0}" == "1" ]] && exit 0 || exit 1
    ;;
  *"daemon-reload"*)
    exit 0
    ;;
  *"user enable blitztext-linux"*)
    exit 0
    ;;
  *)
    exit 1
    ;;
esac
""".strip("\n"),
    )

    return script_path, stub_bin


def _run_script(
    script_path: Path,
    home_dir: Path,
    runtime_dir: Path,
    stub_bin: Path,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home_dir),
            "XDG_RUNTIME_DIR": str(runtime_dir),
            "PATH": f"{stub_bin}{os.pathsep}{env['PATH']}",
        }
    )
    if extra_env:
        env.update(extra_env)
    proc = subprocess.Popen(
        [BASH, str(script_path)],
        cwd=str(script_path.parent),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = proc.communicate()
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)


def test_install_dies_on_invalid_blitztext_no_hotkey_value(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    script_path, stub_bin = _prepare_install_script(tmp_path, repo_root)
    home_dir = tmp_path / "home"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    result = _run_script(
        script_path, home_dir, runtime_dir, stub_bin, extra_env={"BLITZTEXT_NO_HOTKEY": "2"}
    )

    assert result.returncode == 1
    assert "BLITZTEXT_NO_HOTKEY muss 0 oder 1 sein" in result.stderr


def test_install_warns_before_daemon_reload_when_app_is_active(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    script_path, stub_bin = _prepare_install_script(tmp_path, repo_root)
    home_dir = tmp_path / "home"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    result = _run_script(
        script_path,
        home_dir,
        runtime_dir,
        stub_bin,
        extra_env={"BLITZTEXT_NO_HOTKEY": "1", "BT_TEST_APP_ACTIVE": "1"},
    )

    assert result.returncode == 0, result.stderr
    assert "blitztext-linux läuft gerade" in result.stdout
    assert "daemon-reload kann die App unerwartet beenden" in result.stdout
    assert "systemctl --user stop blitztext-linux" in result.stdout


def test_install_stays_quiet_before_daemon_reload_when_app_is_inactive(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    script_path, stub_bin = _prepare_install_script(tmp_path, repo_root)
    home_dir = tmp_path / "home"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    result = _run_script(
        script_path,
        home_dir,
        runtime_dir,
        stub_bin,
        extra_env={"BLITZTEXT_NO_HOTKEY": "1", "BT_TEST_APP_ACTIVE": "0"},
    )

    assert result.returncode == 0, result.stderr
    assert "blitztext-linux läuft gerade" not in result.stdout
    assert "daemon-reload kann die App unerwartet beenden" not in result.stdout


def test_install_completes_and_enables_autostart_when_not_yet_enabled(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    script_path, stub_bin = _prepare_install_script(tmp_path, repo_root)
    home_dir = tmp_path / "home"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    result = _run_script(
        script_path,
        home_dir,
        runtime_dir,
        stub_bin,
        extra_env={"BLITZTEXT_NO_HOTKEY": "1", "BT_TEST_APP_ENABLED": "0"},
    )

    assert result.returncode == 0, result.stderr
    assert "Installation abgeschlossen" in result.stdout
    assert "blitztext-linux.service für Autostart aktiviert" in result.stdout
    service_dst = home_dir / ".config" / "systemd" / "user" / "blitztext-linux.service"
    assert service_dst.exists()
    assert "%BLITZTEXT_DIR%" not in service_dst.read_text(encoding="utf-8")

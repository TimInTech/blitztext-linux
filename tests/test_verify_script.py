from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# NOTE: tests/conftest.py's autouse `_block_real_notifications` fixture patches
# `subprocess.run` process-wide (it patches the shared `subprocess` module via
# `app.notify.subprocess.run`). Resolving real tool paths must therefore use
# `shutil.which`, not `subprocess.run(["which", ...])`.
INFRA_TOOLS = ("grep", "whoami", "stat", "sort", "dirname", "sed")
BASH = shutil.which("bash")


def _symlink_real_tool(stub_bin: Path, name: str) -> None:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"required real tool not found on PATH: {name}")
    (stub_bin / name).symlink_to(resolved)


def _write_stub(stub_bin: Path, name: str, body: str) -> None:
    path = stub_bin / name
    path.write_text(f"#!{BASH}\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def _prepare_verify_script(
    tmp_path: Path,
    repo_root: Path,
    *,
    present_checked_tools: tuple[str, ...] = (),
    fake_groups: str = "",
) -> tuple[Path, Path]:
    """Copies verify.sh into an isolated fake repo and builds a deterministic PATH.

    Returns (script_path, stub_bin_dir). The isolated PATH shadows every
    checked binary (parec/wl-copy/xclip/ydotool/ffmpeg/socat) so results do
    not depend on what happens to be installed on the machine running the
    tests.
    """
    scripts_dir = tmp_path / "repo" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    script_path = scripts_dir / "verify.sh"
    script_path.write_text((repo_root / "scripts" / "verify.sh").read_text(encoding="utf-8"), encoding="utf-8")
    script_path.chmod(0o755)

    stub_bin = tmp_path / "bin"
    stub_bin.mkdir(parents=True, exist_ok=True)
    for tool in INFRA_TOOLS:
        _symlink_real_tool(stub_bin, tool)

    for tool in present_checked_tools:
        _write_stub(stub_bin, tool, "exit 0")

    _write_stub(
        stub_bin,
        "groups",
        f'printf "%s\\n" "{fake_groups}"',
    )
    _write_stub(stub_bin, "id", '[[ "$1" == "-Gn" ]] && printf "%s\\n" "" || echo 0')
    _write_stub(stub_bin, "systemctl", "exit 1")
    _write_stub(stub_bin, "pgrep", "exit 1")

    return script_path, stub_bin


def _run_script(script_path: Path, home_dir: Path, runtime_dir: Path, stub_bin: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home_dir),
            "XDG_RUNTIME_DIR": str(runtime_dir),
            "PATH": str(stub_bin),
            "WAYLAND_DISPLAY": "",
            "DISPLAY": "",
        }
    )
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


def test_verify_fails_and_exits_1_when_required_tools_and_venv_are_missing(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    script_path, stub_bin = _prepare_verify_script(tmp_path, repo_root, present_checked_tools=())
    home_dir = tmp_path / "home"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    result = _run_script(script_path, home_dir, runtime_dir, stub_bin)

    assert result.returncode == 1
    assert "[FAIL]" in result.stdout
    assert ".venv/bin/python nicht gefunden" in result.stdout


def test_verify_config_permissions_pass_when_file_is_0600(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    script_path, stub_bin = _prepare_verify_script(tmp_path, repo_root)
    home_dir = tmp_path / "home"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    config_file = home_dir / ".config" / "blitztext-linux" / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("{}", encoding="utf-8")
    config_file.chmod(0o600)

    result = _run_script(script_path, home_dir, runtime_dir, stub_bin)

    assert "config.json vorhanden und korrekt geschützt (0600)" in result.stdout


def test_verify_config_permissions_warn_when_file_is_more_permissive(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    script_path, stub_bin = _prepare_verify_script(tmp_path, repo_root)
    home_dir = tmp_path / "home"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    config_file = home_dir / ".config" / "blitztext-linux" / "config.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text("{}", encoding="utf-8")
    config_file.chmod(0o644)

    result = _run_script(script_path, home_dir, runtime_dir, stub_bin)

    assert "Berechtigungen sind 644" in result.stdout
    assert "chmod 600" in result.stdout


def test_verify_config_missing_reports_info_not_fail(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    script_path, stub_bin = _prepare_verify_script(tmp_path, repo_root)
    home_dir = tmp_path / "home"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    result = _run_script(script_path, home_dir, runtime_dir, stub_bin)

    assert "config.json nicht gefunden" in result.stdout
    assert "wird beim ersten Start automatisch erstellt" in result.stdout


def test_verify_missing_xdg_runtime_dir_is_reported_as_fail(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    script_path, stub_bin = _prepare_verify_script(tmp_path, repo_root)
    home_dir = tmp_path / "home"

    env = os.environ.copy()
    env.update({"HOME": str(home_dir), "PATH": str(stub_bin), "WAYLAND_DISPLAY": "", "DISPLAY": ""})
    env.pop("XDG_RUNTIME_DIR", None)
    proc = subprocess.Popen(
        [BASH, str(script_path)],
        cwd=str(script_path.parent),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, _ = proc.communicate()

    assert "XDG_RUNTIME_DIR nicht gesetzt" in stdout
    assert proc.returncode == 1


def test_verify_all_checked_binaries_present_removes_their_fail_lines(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    checked_tools = ("parec", "wl-copy", "xclip", "ydotool", "ffmpeg", "socat")
    script_path, stub_bin = _prepare_verify_script(tmp_path, repo_root, present_checked_tools=checked_tools)
    home_dir = tmp_path / "home"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    result = _run_script(script_path, home_dir, runtime_dir, stub_bin)

    for tool in checked_tools:
        assert f"{tool} nicht gefunden" not in result.stdout
        assert f"{tool} gefunden" in result.stdout

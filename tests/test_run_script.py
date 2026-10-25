from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def _prepare_run_script(tmp_path: Path, repo_root: Path) -> Path:
    script_path = tmp_path / "run.sh"
    script_path.write_text((repo_root / "run.sh").read_text(encoding="utf-8"), encoding="utf-8")
    script_path.chmod(0o755)

    stub_python = tmp_path / ".venv" / "bin" / "python"
    stub_python.parent.mkdir(parents=True, exist_ok=True)
    stub_python.write_text(
        "#!/usr/bin/env bash\nprintf 'BT_SAMPLE_VAR=%s\\n' \"${BT_SAMPLE_VAR:-}\"\n",
        encoding="utf-8",
    )
    stub_python.chmod(0o755)

    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "blitztext_linux.py").write_text("print('noop')\n", encoding="utf-8")
    return script_path


def _run_script(script_path: Path, home_dir: Path, runtime_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update({
        "HOME": str(home_dir),
        "XDG_DATA_HOME": str(home_dir / ".local/share"),
        "XDG_RUNTIME_DIR": str(runtime_dir),
    })
    proc = subprocess.Popen(
        ["bash", str(script_path)],
        cwd=str(script_path.parent),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = proc.communicate()
    return subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)


def test_run_script_warns_when_file_is_more_permissive_than_0600(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    script_path = _prepare_run_script(tmp_path, repo_root)
    home_dir = tmp_path / "home"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    env_file = home_dir / ".config" / "blitztext-linux" / "secrets.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("BT_SAMPLE_VAR=from-env\n", encoding="utf-8")
    env_file.chmod(0o644)

    result = _run_script(script_path, home_dir, runtime_dir)

    assert result.returncode == 0
    assert "BT_SAMPLE_VAR=from-env" in result.stdout
    assert "644" in result.stderr
    assert "600" in result.stderr


@pytest.mark.parametrize("mode", [0o440, 0o604])
def test_run_script_warns_when_secrets_file_has_group_or_other_permissions(
    tmp_path: Path, mode: int
):
    repo_root = Path(__file__).resolve().parents[1]
    script_path = _prepare_run_script(tmp_path, repo_root)
    home_dir = tmp_path / "home"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    env_file = home_dir / ".config" / "blitztext-linux" / "secrets.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("BT_SAMPLE_VAR=from-env\n", encoding="utf-8")
    env_file.chmod(mode)

    result = _run_script(script_path, home_dir, runtime_dir)

    assert result.returncode == 0
    assert "BT_SAMPLE_VAR=from-env" in result.stdout
    assert f"{mode:o}" in result.stderr
    assert "600" in result.stderr


def test_run_script_stays_quiet_when_file_permissions_are_0600(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    script_path = _prepare_run_script(tmp_path, repo_root)
    home_dir = tmp_path / "home"
    runtime_dir = tmp_path / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    env_file = home_dir / ".config" / "blitztext-linux" / "secrets.env"
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text("BT_SAMPLE_VAR=from-env\n", encoding="utf-8")
    env_file.chmod(0o600)

    result = _run_script(script_path, home_dir, runtime_dir)

    assert result.returncode == 0
    assert "BT_SAMPLE_VAR=from-env" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize('valid', [True, False])
def test_dispatches_only_ready_managed_release(tmp_path, valid):
    repo = Path(__file__).resolve().parents[1]
    script = _prepare_run_script(tmp_path, repo)
    home = tmp_path / 'home'; runtime = tmp_path / 'runtime'; runtime.mkdir()
    releases = home / '.local/share/blitztext-linux/releases'
    managed = releases / '1.2.0-abcdef'; (managed / 'app').mkdir(parents=True)
    (managed / 'app/blitztext_linux.py').write_text('pass')
    python = managed / '.venv/bin/python'; python.parent.mkdir(parents=True)
    python.write_text('#!/bin/bash\nprintf "managed:%s\\n" "$@"\n'); python.chmod(0o755)
    if valid: (managed / '.ready').touch()
    (releases / 'current').symlink_to(managed.name)
    result = _run_script(script, home, runtime)
    assert result.returncode == 0
    assert ('managed:' in result.stdout) is valid


@pytest.mark.parametrize('current_state', ['missing', 'unready', 'outside'])
def test_previous_fallback_and_managed_launcher_do_not_recurse(tmp_path, current_state):
    repo = Path(__file__).resolve().parents[1]
    home = tmp_path / 'home'; runtime = tmp_path / 'runtime'; runtime.mkdir()
    releases = home / '.local/share/blitztext-linux/releases'
    previous = releases / '1.1.0-abc'; previous.mkdir(parents=True)
    script = _prepare_run_script(previous, repo)
    (previous / '.ready').touch()
    python = previous / '.venv/bin/python'
    python.write_text('#!/bin/bash\nprintf "previous:%s\\n" "$@"\n'); python.chmod(0o755)
    (releases / 'previous').symlink_to(previous.name)
    target = releases / '1.2.0-def'
    if current_state == 'unready': target.mkdir()
    if current_state == 'outside':
        target = tmp_path / 'outside'
        target.mkdir()
        _prepare_run_script(target, repo)
        (target / '.ready').touch()
    (releases / 'current').symlink_to(target)
    result = _run_script(script, home, runtime)
    assert result.returncode == 0
    assert f'previous:{previous}/app/blitztext_linux.py' in result.stdout

from __future__ import annotations

import os
import subprocess
from pathlib import Path


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

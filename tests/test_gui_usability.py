"""Hard usability gates for the main window (click budgets, accessibility).

The same driver feeds ``scripts/gui_usability_check.py``, which also writes
screenshots for the blind LLM review (see ``.claude/skills/gui-usability-review``).
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

_GUI = os.environ.get("WHISPER_GUI_TESTS") == "1"
gui_only = pytest.mark.skipif(not _GUI, reason="benötigt WHISPER_GUI_TESTS=1 (Display)")

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gui_usability_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("gui_usability_check", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    if not _GUI:
        pytest.skip("benötigt WHISPER_GUI_TESTS=1 (Display)")
    return _load().run_checks(tmp_path_factory.mktemp("usability"))


@gui_only
def test_every_task_stays_within_its_click_budget(report):
    over = [(t["id"], t["clicks"], t["budget"]) for t in report["tasks"] if t["clicks"] > t["budget"]]
    assert over == []


@gui_only
def test_every_task_reached_its_goal(report):
    assert [t["id"] for t in report["tasks"] if not t["goal_reached"]] == []


@gui_only
def test_switching_provider_or_model_stays_cheap(report):
    by_id = {t["id"]: t for t in report["tasks"]}
    assert by_id["A_provider"]["clicks"] <= 4
    assert by_id["C_dictate"]["clicks"] <= 3
    assert by_id["D_model"]["clicks"] <= 3
    assert by_id["E_settings"]["clicks"] == 1


@gui_only
def test_every_step_has_a_screenshot(report):
    for task in report["tasks"]:
        for step in task["steps"]:
            assert Path(step["screenshot"]).is_file()


@gui_only
def test_no_blocking_accessibility_findings(report):
    blocking = [f for f in report["audit"] if f["severity"] == "high"]
    assert blocking == []


@gui_only
def test_report_is_json_serialisable(report):
    json.dumps(report)


def test_discard_is_a_one_click_usability_task():
    tasks = {task[0]: task for task in _load().TASKS}
    assert 'F_discard' in tasks
    assert tasks['F_discard'][2] == 1

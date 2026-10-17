"""Drive the main window offscreen, count clicks, grab screenshots, audit widgets.

Usage: QT_QPA_PLATFORM=offscreen python scripts/gui_usability_check.py OUTDIR
Writes OUTDIR/report.json plus one PNG per step. The PNGs and the task text feed
a blind reviewer; the audit part needs no LLM.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MIN_TARGET = 22  # px, the smallest allowed clickable control (header buttons)

# id, title, click budget
TASKS = (
    ("A_provider", "Switch the AI provider to OpenRouter", 4),
    ("B_preset", "Pick the writing style 'Kürzen' for text improvement", 4),
    ("C_dictate", "Dictate with text improvement (start and stop)", 3),
    ("D_model", "Switch the Whisper model to 'tiny'", 3),
    ("E_settings", "Open the settings dialog", 1),
)


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, *args))
        return call


class _Session:
    """Counts clicks and writes one screenshot per user action."""

    def __init__(self, window, app, outdir: Path, task_id: str) -> None:
        self.window, self.app, self.outdir, self.task_id = window, app, outdir, task_id
        self.clicks = 0
        self.steps: list[dict] = []

    def _shot(self, action: str) -> None:
        self.app.processEvents()
        popup = self.window._options_popup
        target = popup if popup.isVisible() else self.window
        path = self.outdir / f"{self.task_id}_{len(self.steps) + 1:02d}.png"
        target.grab().save(str(path))
        self.steps.append({"action": action, "screenshot": str(path)})

    def click(self, button, label: str) -> None:
        self.clicks += 1
        button.click()
        self._shot(f"click: {label}")

    def choose(self, combo, data, label: str) -> None:
        """Opening a drop-down and picking an entry is two clicks."""
        self.clicks += 2
        combo.setCurrentIndex(combo.findData(data))
        self._shot(f"choose: {label}")


def _controller_task(task_id, window, app, outdir, recorder):
    s = _Session(window, app, outdir, task_id)
    from app.workflows import WorkflowType

    if task_id == "A_provider":
        s.click(window._seg_ai, "Mit KI")
        s.click(window._mode_label, "Zustandszeile (Details)")
        s.choose(window._provider_combo, "openrouter", "KI-Anbieter")
        goal = ("provider", "openrouter") in recorder.calls
    elif task_id == "B_preset":
        s.click(window._seg_ai, "Mit KI")
        s.click(window._mode_label, "Zustandszeile (Details)")
        s.choose(window._preset_combo, "shorten", "Vorlage")
        goal = ("main_window_preset_changed", "shorten") in recorder.calls
        goal = goal or ("preset", "shorten") in recorder.calls
    elif task_id == "C_dictate":
        s.click(window._seg_ai, "Mit KI")
        window.update_state("IDLE", WorkflowType.TEXT_IMPROVER, None)
        s.click(window._btn_toggle, "Start")
        # The real controller moves the window through its states; mirror that.
        window.update_state("RECORDING", WorkflowType.TEXT_IMPROVER, None)
        s._shot("state: recording")
        s.click(window._btn_toggle, "Stopp")
        window.update_state("LLM_REWRITING", WorkflowType.TEXT_IMPROVER, None)
        s._shot("state: improving")
        toggles = [c for c in recorder.calls if c[0] == "gui_toggle_recording"]
        goal = len(toggles) == 2 and toggles[0][1] == WorkflowType.TEXT_IMPROVER
    elif task_id == "D_model":
        window.set_model("base")
        s.click(window._mode_label, "Zustandszeile (Details)")
        s.choose(window._model_combo, "tiny", "Whisper-Modell")
        goal = ("model", "tiny") in recorder.calls
    else:
        s.click(window._btn_settings, "Zahnrad")
        goal = ("show_settings_dialog",) in recorder.calls
        _shot_settings_dialog(s)
    window._options_popup.hide()
    return {"clicks": s.clicks, "steps": s.steps, "goal_reached": bool(goal)}


def _shot_settings_dialog(session) -> None:
    """The fake controller opens nothing, so grab what the real dialog looks like."""
    import tempfile

    from app.blitztext_linux import SettingsDialog
    from app.config import BlitztextConfig

    with tempfile.TemporaryDirectory() as tmp:
        dialog = SettingsDialog(BlitztextConfig(config_dir=Path(tmp)))
        dialog.show()
        session.app.processEvents()
        path = session.outdir / f"{session.task_id}_{len(session.steps) + 1:02d}.png"
        dialog.grab().save(str(path))
        session.steps.append({"action": "result: settings dialog opens", "screenshot": str(path)})
        dialog.close()


def audit_widgets(window) -> list[dict]:
    """Return accessibility findings for every interactive widget of the window."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QComboBox, QPushButton

    findings: list[dict] = []
    window._show_options_popup()
    # The popup is a child of the window, so one pass sees every control once.
    for widget in window.findChildren((QPushButton, QComboBox)):
        name = widget.objectName() or type(widget).__name__
        label = widget.accessibleName() or widget.toolTip() or getattr(widget, "text", lambda: "")()
        size = widget.size() if widget.isVisible() else widget.sizeHint()
        if not label:
            findings.append({"widget": name, "severity": "high", "issue": "no accessible name, tooltip or text"})
        if widget.focusPolicy() == Qt.FocusPolicy.NoFocus:
            findings.append({"widget": name, "severity": "medium", "issue": "not reachable by keyboard"})
        if min(size.width(), size.height()) < MIN_TARGET:
            findings.append({
                "widget": name, "severity": "high",
                "issue": f"target {size.width()}x{size.height()} px is below {MIN_TARGET} px",
            })
    window._options_popup.hide()
    return findings


def _checked_outdir(outdir: Path) -> Path:
    """Resolve the output directory and only accept the working tree or the temp dir."""
    resolved = os.path.realpath(str(outdir))
    allowed = [os.path.realpath(os.getcwd()), os.path.realpath(tempfile.gettempdir())]
    if not any(resolved == base or resolved.startswith(base + os.sep) for base in allowed):
        raise SystemExit(f"output directory must be inside the working tree or the temp dir: {resolved}")
    return Path(resolved)


def run_checks(outdir: Path) -> dict:
    from PyQt6.QtWidgets import QApplication

    from app.main_window import MainWindow

    outdir = _checked_outdir(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    tasks = []
    for task_id, title, budget in TASKS:
        recorder = _Recorder()
        # Provider/model/preset calls arrive under their controller method names.
        controller = SimpleNamespace(
            gui_toggle_recording=lambda wf, r=recorder: r.calls.append(("gui_toggle_recording", wf)),
            gui_discard=lambda r=recorder: r.calls.append(("gui_discard",)),
            set_dictation_mode=lambda e, r=recorder: r.calls.append(("dictation", e)),
            show_compose_window=lambda r=recorder: r.calls.append(("compose",)),
            show_custom_prompt=lambda r=recorder: r.calls.append(("prompt",)),
            show_history_panel=lambda r=recorder: r.calls.append(("history",)),
            show_tts_window=lambda r=recorder: r.calls.append(("tts",)),
            show_settings_dialog=lambda r=recorder: r.calls.append(("show_settings_dialog",)),
            main_window_preset_changed=lambda k, r=recorder: r.calls.append(("preset", k)),
            main_window_provider_changed=lambda p, r=recorder: r.calls.append(("provider", p)),
            main_window_model_changed=lambda m, r=recorder: r.calls.append(("model", m)),
        )
        window = MainWindow(controller)
        window.show()
        app.processEvents()
        result = _controller_task(task_id, window, app, outdir, recorder)
        window.close()
        tasks.append({"id": task_id, "title": title, "budget": budget, **result})
    window = MainWindow(SimpleNamespace(**{
        n: (lambda *a, **k: None) for n in (
            "gui_toggle_recording gui_discard set_dictation_mode show_compose_window show_custom_prompt "
            "show_history_panel show_tts_window show_settings_dialog main_window_preset_changed "
            "main_window_provider_changed main_window_model_changed").split()
    }))
    window.show()
    app.processEvents()
    audit = audit_widgets(window)
    window.close()
    report = {"tasks": tasks, "audit": audit}
    (outdir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "gui-review-out")
    result = run_checks(out)
    for task in result["tasks"]:
        print(f"{task['id']}: {task['clicks']} clicks (budget {task['budget']}), goal={task['goal_reached']}")
    for finding in result["audit"]:
        print(f"AUDIT {finding['severity']}: {finding['widget']} - {finding['issue']}")

---
name: gui-usability-review
description: Reproducible usability review of the Blitztext main window - offscreen clicks, screenshots, hard accessibility checks and a blind LLM rating. Use after changing app/main_window.py, theme.py or popup/toolbar layout.
---

# GUI usability review

## Purpose
Measure how quickly a user reaches common goals in the Qt main window and catch
accessibility defects, without a desktop session.

## Trigger
Any change to `app/main_window.py`, `app/theme.py`, toolbar/popup controls or the
controller methods the window calls.

## Inputs
- `scripts/gui_usability_check.py` (task list `TASKS`, click budgets)
- `tests/test_gui_usability.py` (hard gates)

## Procedure
1. Run the driver: `QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/gui_usability_check.py`.
   It prints a fresh temp directory containing `report.json` and one PNG per click step; copy what you want to keep.
2. Hard gates (no LLM): `WHISPER_GUI_TESTS=1 QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q tests/test_gui_usability.py`.
   Click budgets, goal reached, accessible names, keyboard focus, minimum target 22 px.
3. Blind LLM rating, at least 3 independent runs per task. The reviewer gets ONLY
   the task text and the PNG sequence of that task - never code, never this file's
   results. Use a fresh subagent per run.
4. Reviewer output, JSON only:
   `{"task": id, "score": 1-5, "findings": [{"widget": "...", "severity": "low|medium|high", "issue": "..."}], "suggestion": "..."}`
5. Score = mean over runs. Store under `.omc/uebergabe/gui-review/<date>/`, compare with the frozen baseline.

## Rubric (score 1-5 per task)
Findability of the control, number of steps, label clarity, feedback after the
action (is the new state visible?), error/edge handling, target size and contrast.
5 = obvious and immediate, 3 = works but needs hunting, 1 = most users fail.

## Verification
Hard gates green; mean score not below the baseline; no high-severity finding unaddressed.

## Rollback / abort
The driver only reads the UI with a fake controller; nothing to roll back. Abort the
review if the screenshots are blank (check `QT_QPA_PLATFORM=offscreen`).

## Known pitfalls
- A drop-down counts as two clicks (open, choose); the driver sets the combo index directly, so budgets are assumed clicks, not measured ones.
- Offscreen renders no native Wayland decorations or real fonts; judge layout, not font metrics.
- Setting a combo to its current value emits no signal; set a different state first.
- Reviewer prompts must never include the source, or the rating is no longer blind.

## References
`app/main_window.py`, `scripts/gui_usability_check.py`, Nielsen's 10 usability heuristics.

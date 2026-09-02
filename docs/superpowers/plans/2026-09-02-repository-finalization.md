# Repository Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or direct TDD execution task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the repaired `main` is healthy, remove the merged branch residue, and leave GitHub without open review debt.

**Architecture:** This operational plan runs only after the code-hardening plan. It turns local evidence into GitHub state in a fixed order: install missing dev dependency, verify locally, push main, wait for CI success, resolve only verified threads, then delete only the known tree-equivalent branch.

**Tech Stack:** Git, GitHub Actions, GitHub review-thread API, Python pytest, Bash.

**Spec:** `docs/superpowers/specs/2026-09-02-repository-cleanup-design.md`

## Global Constraints

- Do not resolve a review thread before a current-code test or direct source verification proves it addressed.
- Do not delete `fix/hold-short-press-recovery` until `git diff --exit-code d27afd9 6bb8ec4` succeeds and current main CI succeeds.
- Do not force-push, rewrite history, or close issues/PRs merely to improve dashboard appearance.
- `.codex/config.toml` is local machine state; add it only to `.git/info/exclude`, never to a commit.

---

## Task 1: Establish a complete local verification environment

**Files:**

- Local-only modify: `.git/info/exclude`
- No tracked-file change required unless `requirements-dev.txt` lacks Pillow.

- [ ] **Step 1: Add the exact local-only exclusion**

Append this line only if it is absent:

```text
.codex/
```

Use `.git/info/exclude`, not `.gitignore`, because `.codex/config.toml` contains machine-specific Codex launch configuration.

- [ ] **Step 2: Install declared development dependencies**

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -c "from PIL import Image; print(Image.__version__)"
```

Expected: Pillow imports successfully; it is already declared in `requirements-dev.txt` and therefore no dependency commit is needed.

- [ ] **Step 3: Verify the previously failed ydotool tests**

```bash
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/test_state_machine.py::TestPasteTimeouts::test_paste_uses_configured_key_delay_for_ydotool tests/test_state_machine.py::TestPasteTimeouts::test_force_autopaste_override_enables_ydotool -q
```

Expected: `2 passed`. This verifies the existing commit `8f4468d` against the current ydotool syntax probe.

## Task 2: Full local gates

- [ ] **Step 1: Compile and run every test**

```bash
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m compileall -q app
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/ -q
```

Expected: no failure and no Pillow-related collection skip; any intended platform skip must be reported separately with its reason.

- [ ] **Step 2: Verify scripts and repository integrity**

```bash
bash -n run.sh scripts/install.sh scripts/verify.sh
bash scripts/verify.sh
git diff --check origin/main...HEAD
git fsck --no-dangling
```

Expected: syntax and integrity checks exit 0; `verify.sh` reports no failures or warnings for this known host.

- [ ] **Step 3: Run the tracked secret scan exactly as CI does**

```bash
patterns_file=.github/secret-scan-patterns.txt
pattern="$(grep -vE '^[[:space:]]*(#|$)' "$patterns_file" | paste -sd'|' -)"
! grep -RInE --exclude-dir=.git --exclude=secret-scan-patterns.txt "$pattern" .
```

Expected: no match. If a match is present, inspect it as a possible secret and do not push.

## Task 3: Push main and wait for the authoritative CI matrix

- [ ] **Step 1: Confirm only intended commits are outgoing**

```bash
git status --short --branch
git log --oneline origin/main..HEAD
git diff --check origin/main...HEAD
```

- [ ] **Step 2: Push without history rewrite**

```bash
git push origin main
```

- [ ] **Step 3: Inspect the workflow run for the pushed SHA**

Query GitHub Actions for the exact head SHA. Require:

```text
Secret hygiene scan: success
Tests (Python 3.11): success
Tests (Python 3.12): success
Tests (Python 3.14): success
```

If any job is not `completed/success`, retrieve its job log, add a regression test for the reported failure, fix it locally, repeat Task 2, and push the normal follow-up commit. Do not resolve threads or delete branches while CI is red.

## Task 4: Resolve each verified historical review thread

**Threads:**

- #7: `PRRT_kwDOS8wgHs6KYgYS`, `PRRT_kwDOS8wgHs6KYgYY`
- #10: `PRRT_kwDOS8wgHs6K4Fz2`, `PRRT_kwDOS8wgHs6K4Fz8`
- #13: `PRRT_kwDOS8wgHs6K8fQe`
- #14: `PRRT_kwDOS8wgHs6LCGZn`
- #15: `PRRT_kwDOS8wgHs6LDJ6J`, `PRRT_kwDOS8wgHs6LDJ6K`
- #17: `PRRT_kwDOS8wgHs6LD4Z8`, `PRRT_kwDOS8wgHs6LD4Z-`
- #18: `PRRT_kwDOS8wgHs6LGSmR`
- #21: `PRRT_kwDOS8wgHs6LOHC1`
- #38: `PRRT_kwDOS8wgHs6NvFfM`, `PRRT_kwDOS8wgHs6NvFfP`
- #40: `PRRT_kwDOS8wgHs6N57G6`
- #42: `PRRT_kwDOS8wgHs6OVs5r`
- #44: `PRRT_kwDOS8wgHs6OV6KR`
- #47: `PRRT_kwDOS8wgHs6OdFwO`
- #53: `PRRT_kwDOS8wgHs6SZcCP`, `PRRT_kwDOS8wgHs6SZcCR`
- #55: `PRRT_kwDOS8wgHs6YAYC_`
- #56: `PRRT_kwDOS8wgHs6ZFzUk`
- #57: `PRRT_kwDOS8wgHs6drhy6`, `PRRT_kwDOS8wgHs6drhzA`
- #58: `PRRT_kwDOS8wgHs6dw0Pb`

- [ ] **Step 1: Verify the three already-resolved-in-code items**

```bash
rg -n "mkstemp|Pillow|_read_clipboard" app/tts_window.py requirements-dev.txt tests/test_state_machine.py
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/test_make_demo_gif.py tests/test_make_screenshots.py tests/test_state_machine.py -q
```

The expected evidence is: ffmpeg temp paths remain reserved, Pillow imports from the declared dev dependency, and the clipboard restoration test mocks `_read_clipboard`.

- [ ] **Step 2: Resolve only after evidence exists**

Call GitHub's review-thread resolve operation once for each listed thread after its matching test or source proof and green current main CI have been recorded.

- [ ] **Step 3: Re-query every PR thread list**

For PRs `7, 10, 13, 14, 15, 17, 18, 21, 38, 40, 42, 44, 47, 53, 55, 56, 57, 58`, query `list_pull_request_review_threads` and require `is_resolved: true` for every inventory ID. Stop if an unknown unresolved thread appears and assess it before claiming completion.

## Task 5: Delete only the verified obsolete branches

- [ ] **Step 1: Re-prove branch equivalence**

```bash
git fetch origin --prune
git diff --exit-code d27afd95ddf27c15183036b0fbd91529cd099593 6bb8ec4f861084dffc314cb4260691e65f11fa62
git branch -vv
```

Expected: zero diff; local `codex/pr56-conflict-resolution` tracks only the obsolete remote fix branch.

- [ ] **Step 2: Delete the exact remote branch**

```bash
git push origin --delete fix/hold-short-press-recovery
```

- [ ] **Step 3: Delete the exact local branch**

```bash
git branch -D codex/pr56-conflict-resolution
git fetch origin --prune
```

The forced local delete is safe only because Step 1 established content equality; PR #56 and its commits remain reachable in GitHub history.

## Task 6: Final repository audit

- [ ] **Step 1: Verify local and remote branch cardinality**

```bash
git status --short --branch
git branch --format='%(refname:short)'
git branch -r --format='%(refname:short)'
```

Expected: local `main`; remote `origin/main` only; `main` is not ahead or behind.

- [ ] **Step 2: Verify GitHub state**

Require from GitHub API/connector:

```text
branches = [main]
open pull requests = 0
open issues = 0
unresolved inventory review threads = 0
latest regular BlitztextLinux CI for current main SHA = completed/success
```

- [ ] **Step 3: Record final evidence**

Run the complete commands from Tasks 1 and 2 one final time after branch deletion. Report the exact test count, CI run URL, and branch lists; do not report completion without those fresh outputs.

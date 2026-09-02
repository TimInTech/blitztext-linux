# Code Hardening Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or direct TDD execution task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate every still-applicable historical review finding in the Python application without broad refactoring.

**Architecture:** Keep all existing public behavior and repair the failing boundaries where untrusted configuration, provider state, asynchronous completion, clipboard backends, UI state, and installer diagnostics meet the application. Each task starts with a focused regression test in the existing test module, makes the smallest production change, and commits only the focused files.

**Tech Stack:** Python 3.11–3.14, PyQt6, pytest, Bash, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-02-repository-cleanup-design.md`

## Global Constraints

- Do not store secrets, tokens, passwords, cookies, or private paths.
- Every actual behavior change follows Red-Green-Refactor and records the observed RED failure.
- Do not weaken endpoint validation or replace a security fix with documentation.
- Preserve the existing provider, config, PyQt, and test idioms; do not introduce a new subsystem.
- Keep commits small and use Conventional Commit messages.
- Do not push until the separate finalization plan has completed local verification.
- Use `QT_QPA_PLATFORM=offscreen` and `WHISPER_GUI_TESTS=1` for GUI tests.

---

## File Structure

| File | Responsibility in this plan |
| --- | --- |
| `app/config.py` | Typed config sanitization, blocked invalid non-OpenAI endpoints. |
| `app/blitztext_linux.py` | Atomic settings application, provider-key selection, safe worker error logging, tray/i18n/routing state. |
| `app/tts_window.py` | Explicit Cloud-TTS consent and stale completion suppression. |
| `app/paste_service.py` | Clipboard restore ordering and Qt fallback read/write affinity. |
| `app/hotkey_service.py` | Release the debounce after a discarded short hold. |
| `app/main_window.py`, `app/compose_window.py`, `app/writing_presets.py`, `app/i18n.py` | Refreshing live UI and preserving compose intent. |
| `scripts/verify.sh`, `scripts/install.sh`, `run.sh`, `docs/setup.md` | Host checks, permission checks, and single-instance startup guidance. |
| `tests/test_*.py` | Focused regressions beside existing tests for each module. |

## Task 1: Provider credentials and endpoint state

**Threads:** PR #7 (`3432085972`, `3432085978`), PR #17 (`3447812161`), PR #57 (`3893466915`, `3893466926`).

**Files:**

- Modify: `app/config.py:117-138, 199-204, 461-512`
- Modify: `app/blitztext_linux.py:SettingsDialog._on_llm_provider_changed, SettingsDialog.save_settings, BlitztextApp._build_llm_service`
- Test: `tests/test_config.py`
- Test: `tests/test_settings_dialog.py`

**Interfaces:**

- `BlitztextConfig` must expose a boolean blocked-endpoint state for a migrated invalid `custom` or `openrouter` endpoint.
- `SettingsDialog.save_settings()` must validate all candidate values before changing the shared `BlitztextConfig` instance.
- `_build_llm_service()` must refuse a non-OpenAI provider lacking a valid explicit endpoint and must never create an OpenAI-default client from such state.

- [ ] **Step 1: Write the failing config tests**

```python
def test_non_utf8_config_falls_back_to_defaults(config_dir):
    (config_dir / "config.json").write_bytes(b"\xff\xfe")
    config = Config.load(config_dir / "config.json")
    assert config.llm_provider == "openai"

def test_unsafe_custom_endpoint_blocks_llm_requests(config_dir):
    (config_dir / "config.json").write_text(
        json.dumps({"llm_provider": "custom", "llm_base_url": "http://api.example.com/v1"}),
        encoding="utf-8",
    )
    config = Config.load(config_dir / "config.json")
    assert config.has_unsafe_llm_base_url is True
    assert config.has_blocked_llm_endpoint is True
```

Add settings-dialog tests using the existing `_FakeSettingsDialog`: changing the combo to `openrouter` changes `edit_api_key_env` away from `OPENAI_API_KEY`; an empty `custom` or `openrouter` endpoint is rejected; and a rejected endpoint leaves every previously configured field unchanged.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```bash
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/test_config.py tests/test_settings_dialog.py -q
```

Expected: non-UTF-8 loading raises `UnicodeDecodeError`; a migrated unsafe non-OpenAI endpoint has no blocked state; provider switch retains `OPENAI_API_KEY`; and a rejected save has mutated in-memory config fields.

- [ ] **Step 3: Implement the minimal config and settings changes**

```python
# app/config.py
except (json.JSONDecodeError, UnicodeDecodeError, OSError):
    return _deep_merge(DEFAULTS, {})

# set only when an unsafe URL belonged to custom/openrouter
self._blocked_llm_endpoint = (
    self._data.get("llm_provider") in {"custom", "openrouter"}
    and invalid_endpoint_was_removed
)
```

Add `has_blocked_llm_endpoint`. In `save_settings()`, first build local candidate variables, validate `base_url` and provider-specific non-emptiness, then assign the candidates and persist. Set a distinct, documented OpenRouter environment-variable default only when the user has not customized the field; for custom providers leave the field explicit. In `_build_llm_service()`, raise the existing user-facing configuration error before resolving a key whenever a non-OpenAI provider is blocked or has an empty endpoint.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2. Expected: all selected tests pass and no API client is built for an invalid non-OpenAI configuration.

- [ ] **Step 5: Commit provider/config hardening**

```bash
git add app/config.py app/blitztext_linux.py tests/test_config.py tests/test_settings_dialog.py
git commit -m "fix: harden provider endpoint configuration"
```

## Task 2: Cloud-TTS consent and cancellation

**Threads:** PR #10 (`3443475472`, `3443475480`).

**Files:**

- Modify: `app/config.py:359-365, 491`
- Modify: `app/tts_window.py:868-943` and the cloud-worker signal wiring
- Test: `tests/test_features.py`

**Interfaces:**

- `tts_openai_consent` is true only for the JSON boolean `true`.
- A cloud result may start playback/export only if it belongs to the active, non-cancelled cloud request.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("stored", ["true", "false", "no", 1, [], {}])
def test_non_boolean_cloud_tts_consent_is_false(config_dir, stored):
    (config_dir / "config.json").write_text(json.dumps({"tts_openai_consent": stored}), encoding="utf-8")
    assert Config.load(config_dir / "config.json").tts_openai_consent is False

def test_cloud_completion_after_stop_does_not_start_playback():
    fake = make_cancelled_cloud_window()
    TtsWindow._on_cloud_finished(fake, "/tmp/result.wav")
    fake._start_export_process.assert_not_called()
    fake._aplay_proc.start.assert_not_called()
```

Use the existing `SimpleNamespace`/`MagicMock` TTS test style and construct `make_cancelled_cloud_window()` with no active request identity.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/test_features.py -q
```

Expected: strings such as `"false"` are truthy and `_on_cloud_finished()` starts playback after cloud state was detached.

- [ ] **Step 3: Implement explicit consent and request identity**

```python
# app/config.py
self._data["tts_openai_consent"] = self._data.get("tts_openai_consent") is True

# app/tts_window.py
if worker is not self._cloud_worker or worker.cancel_requested:
    return
```

Wire `finished` through a lambda that captures its worker (or an incrementing request id), and keep `_on_cloud_finished`'s public slot behavior otherwise unchanged. Increment/invalidate the request identity before `_detach_cloud_thread()` clears active state.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the command from Step 2. Expected: existing consent/export tests and the new cancellation regression all pass.

- [ ] **Step 5: Commit Cloud-TTS lifecycle fix**

```bash
git add app/config.py app/tts_window.py tests/test_features.py
git commit -m "fix: guard cloud tts consent and cancellation"
```

## Task 3: Sanitize provider errors before every log sink

**Thread:** PR #58 (`3895519777`).

**Files:**

- Modify: `app/blitztext_linux.py` in the worker-error handler around the `BLITZTEXT_DEBUG` branch
- Test: `tests/test_state_machine.py` or the existing error-classification test module

- [ ] **Step 1: Write a failing debug-log regression**

```python
def test_worker_error_debug_log_masks_provider_bearer_token(caplog, monkeypatch):
    monkeypatch.setenv("BLITZTEXT_DEBUG", "1")
    app = make_app_for_worker_error()
    app._on_worker_error("provider failed Authorization: Bearer sk-test-secret")
    assert "sk-test-secret" not in caplog.text
    assert "[REDACTED]" in caplog.text
```

- [ ] **Step 2: Run RED**

```bash
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/test_state_machine.py -q
```

Expected: the raw provider error appears in the debug record.

- [ ] **Step 3: Sanitize once at the boundary**

```python
safe_error = sanitize_external_error(error_message)
logger.debug("Worker error: %s", safe_error)
```

Pass `safe_error`, rather than the raw message, to every subsequent tray, notification, and UI path in the handler.

- [ ] **Step 4: Run GREEN and commit**

```bash
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/test_state_machine.py tests/test_llm_service.py -q
git add app/blitztext_linux.py tests/test_state_machine.py
git commit -m "fix: sanitize worker error debug logs"
```

## Task 4: Clipboard backend correctness

**Threads:** PR #38 (`3509426735`; its test-mock thread is already fixed), PR #47 (`3525740400`, `3525740401`, `3525821601`).

**Files:**

- Modify: `app/paste_service.py:139-147, 376-427`
- Test: `tests/test_paste_service.py`
- Test: `tests/test_flatpak_fallback.py`

- [ ] **Step 1: Write failing regressions**

```python
def test_paste_cleans_copyq_before_restoring_previous_clipboard():
    calls = []
    service = PasteService(autopaste=True)
    with patch.object(service, "_read_clipboard", return_value="old"), \
         patch.object(service, "_copy_to_clipboard"), \
         patch.object(service, "_ydotool_paste", return_value=True), \
         patch.object(service, "_cleanup_copyq", side_effect=lambda text: calls.append("cleanup")), \
         patch.object(service, "_restore_clipboard", side_effect=lambda text: calls.append("restore")):
        service.paste("new")
    assert calls == ["cleanup", "restore"]

def test_qt_read_from_worker_marshals_to_gui_thread(qapp):
    service = PasteService()
    assert run_qt_read_from_qthread(service) == "existing clipboard"
```

Keep the existing Qt fallback fixture and add the matching Qt restoration assertion: after a successful fallback auto-paste, the fake clipboard again contains its previous value.

- [ ] **Step 2: Run RED**

```bash
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/test_paste_service.py tests/test_flatpak_fallback.py -q
```

Expected: CopyQ is called after restore; worker-thread Qt reads return `None`; and fallback tests do not cover reliable restore.

- [ ] **Step 3: Implement ordering and GUI-thread marshaling**

```python
if do_autopaste and self._ydotool_paste():
    time.sleep(_PASTE_DELAY)
    self._cleanup_copyq(text)
    self._restore_clipboard(previous_clipboard)
```

Extract a small `QObject` clipboard bridge with `@pyqtSlot()` methods for both `read_text` and `set_text`, move it to `QApplication.instance().thread()`, and invoke both methods with `Qt.ConnectionType.BlockingQueuedConnection` when called from a worker. Preserve the no-Qt/no-clipboard fallbacks.

- [ ] **Step 4: Run GREEN and commit**

```bash
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/test_paste_service.py tests/test_flatpak_fallback.py tests/test_state_machine.py -q
git add app/paste_service.py tests/test_paste_service.py tests/test_flatpak_fallback.py
git commit -m "fix: preserve clipboard across fallback paste"
```

## Task 5: Hotkey and compose delivery state

**Threads:** PR #53 (`3617921339`, `3617921343`), PR #56 (`3779261539`).

**Files:**

- Modify: `app/hotkey_service.py:292-333`
- Modify: `app/compose_window.py:603-616, 799-806`
- Modify: `app/blitztext_linux.py` around recording-start state capture and worker-result routing
- Test: `tests/test_state_machine.py`
- Test: `tests/test_compose_window.py`

- [ ] **Step 1: Write failing event and draft regressions**

```python
def test_short_hold_allows_immediate_corrective_hold():
    triggered, stopped, discarded = _run_worker_with_events(
        [(_KEYCODES["KEY_LEFTALT"], 1), (_KEYCODES["KEY_LEFTALT"], 0), (_KEYCODES["KEY_LEFTALT"], 1)],
        hotkey_mode="hold",
        monotonic_values=[10.0, 10.0, 10.0, 10.149, 10.200],
    )
    assert triggered == [WorkflowType.TRANSCRIPTION, WorkflowType.TRANSCRIPTION]
    assert stopped == []
    assert discarded == [True]

def test_routed_voice_result_appends_to_existing_compose_draft(compose_window):
    compose_window.set_input_text("Existing draft")
    compose_window.append_routed_voice_text(" dictation")
    assert compose_window._input.toPlainText() == "Existing draft dictation"
```

Add a state-machine test that closes the routed compose window after recording begins and asserts the result uses the normal clipboard/autopaste delivery path.

- [ ] **Step 2: Run RED**

```bash
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/test_state_machine.py tests/test_compose_window.py -q
```

Expected: only one trigger is emitted after the short hold; `set_input_text` replaces the draft; and routing remains active after the window closes.

- [ ] **Step 3: Implement minimal state changes**

```python
# app/hotkey_service.py, discard branch
last_trigger.pop(_hold_active, None)
self.recording_discard.emit()
```

Add `ComposeWindow.append_routed_voice_text(text)` that inserts at the input cursor without clearing variants/output. Store the intended compose window itself at recording start, then at result time route only when it is still visible and `voice_routing_enabled()`; otherwise use the existing non-routed result path.

- [ ] **Step 4: Run GREEN and commit**

```bash
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/test_state_machine.py tests/test_compose_window.py -q
git add app/hotkey_service.py app/compose_window.py app/blitztext_linux.py tests/test_state_machine.py tests/test_compose_window.py
git commit -m "fix: recover routed and hold recordings"
```

## Task 6: Live localization and prompt preservation

**Threads:** PR #14 (`3447197833`), PR #15 (`3447570018`, `3447570020`), PR #44 (`3523325000`).

**Files:**

- Modify: `app/main_window.py`, `app/compose_window.py`, `app/history_panel.py`, `app/tts_window.py`, `app/blitztext_linux.py`, `app/writing_presets.py`
- Test: `tests/test_smoke_launch.py`, `tests/test_compose_window.py`, `tests/test_i18n.py`, `tests/test_llm_service.py`

- [ ] **Step 1: Write failing localized-widget and preset tests**

```python
def test_refresh_i18n_updates_live_main_and_tray_actions(qapp):
    app = make_running_app(language="en")
    set_language("de")
    app._refresh_i18n_texts()
    assert app._main_window.btn_toggle.text() == t("main.start")
    assert app.action_dictation.text() == t("tray.dictation")
    assert app.action_history.text() == t("tray.history")
    assert app.action_tts.text() == t("tray.tts")

@pytest.mark.parametrize("preset", non_standard_preset_keys())
def test_prompt_request_remains_usable_for_every_preset(preset):
    assert "directly usable prompt" in build_system_prompt(preset=preset).lower()
```

Cover a visible `HistoryPanel`, `TtsWindow`, and `ComposeWindow` with their `refresh_i18n()` method where present; do not merely assert a global language variable.

- [ ] **Step 2: Run RED**

```bash
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/test_smoke_launch.py tests/test_compose_window.py tests/test_i18n.py tests/test_llm_service.py -q
```

Expected: existing widgets and tray actions retain their prior-language text, and non-standard prompts omit the usable-prompt exception.

- [ ] **Step 3: Implement explicit refreshes and shared prompt rule**

Add or complete `refresh_i18n()` for each currently live widget and invoke each from `BlitztextApp._refresh_i18n_texts()`. Update every translated tray action in that method. Move the prompt-request exception into the common preset intent rules consumed by every writing preset, without changing unrelated preset language.

- [ ] **Step 4: Run GREEN and commit**

```bash
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/test_smoke_launch.py tests/test_compose_window.py tests/test_i18n.py tests/test_llm_service.py -q
git add app/main_window.py app/compose_window.py app/history_panel.py app/tts_window.py app/blitztext_linux.py app/writing_presets.py tests/test_smoke_launch.py tests/test_compose_window.py tests/test_i18n.py tests/test_llm_service.py
git commit -m "fix: refresh live translations and prompt presets"
```

## Task 7: Tray persistence, scripts, and session diagnostics

**Threads:** PR #13 (`3445022369`), PR #17 (`3447812163`), PR #40 (`3513302256`), PR #42 (`3523254892`), PR #55 (`3752692317`).

**Files:**

- Modify: `app/blitztext_linux.py` tray-preset action path
- Modify: `run.sh`
- Modify: `scripts/verify.sh`
- Modify: `scripts/install.sh`
- Modify: `docs/setup.md`
- Test: `tests/test_tray_preset_menu.py`, `tests/test_run_script.py`, `tests/test_install_script.py`, `tests/test_verify_script.py`

- [ ] **Step 1: Write failing focused tests**

```python
def test_tray_preset_save_failure_reverts_checked_action_and_notifies():
    app = make_app_with_failing_config_save()
    app._on_preset_action_triggered("email_formal")
    assert app.config.writing_preset == "standard"
    assert app.tray.showMessage.called

@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644])
def test_run_script_warns_when_group_or_other_can_read(mode, tmp_path):
    assert run_script_with_secrets_mode(mode).returncode == 0
    assert "permissions" in run_script_with_secrets_mode(mode).stderr.lower()

def test_verify_uses_xclip_when_wayland_variable_has_no_socket(tmp_path):
    result = run_verify({"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0", "XDG_RUNTIME_DIR": str(tmp_path)})
    assert "Clipboard-Backend für diese Session: xclip (Pflicht)" in result.stdout
```

Make install-script tests skip with an explicit `pytest.mark.skipif(os.geteuid() == 0, ...)`, because root cannot exercise the intended non-root installer paths safely. Add a documentation assertion that the manual `run.sh` test process is quit before starting the user service.

- [ ] **Step 2: Run RED**

```bash
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/test_tray_preset_menu.py tests/test_run_script.py tests/test_install_script.py tests/test_verify_script.py -q
```

Expected: tray action leaves a false selected state, loose octal modes are not warned, and a stale Wayland variable selects `wl-copy`.

- [ ] **Step 3: Implement narrow handling**

Catch `ConfigError` in the tray preset slot, restore the prior preset/action check state, and use the existing user notification route. In `run.sh`, parse `stat -c %a` as octal and reject any `(mode & 0o077) != 0`. In `verify.sh`, treat Wayland as active only when `${XDG_RUNTIME_DIR}/${WAYLAND_DISPLAY}` is a socket; otherwise follow the X11 path when `DISPLAY` is set. Add the explicit manual-instance stop instruction immediately before `systemctl --user start blitztext-linux.service`.

- [ ] **Step 4: Run GREEN, syntax checks, and commit**

```bash
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/test_tray_preset_menu.py tests/test_run_script.py tests/test_install_script.py tests/test_verify_script.py -q
bash -n run.sh scripts/install.sh scripts/verify.sh
git add app/blitztext_linux.py run.sh scripts/verify.sh scripts/install.sh docs/setup.md tests/test_tray_preset_menu.py tests/test_run_script.py tests/test_install_script.py tests/test_verify_script.py
git commit -m "fix: harden tray persistence and platform checks"
```

## Task 8: Package-level verification

**Files:** all files touched by Tasks 1–7.

- [ ] **Step 1: Run focused test modules together**

```bash
QT_QPA_PLATFORM=offscreen WHISPER_GUI_TESTS=1 .venv/bin/python -m pytest tests/test_config.py tests/test_settings_dialog.py tests/test_features.py tests/test_paste_service.py tests/test_flatpak_fallback.py tests/test_state_machine.py tests/test_compose_window.py tests/test_smoke_launch.py tests/test_i18n.py tests/test_llm_service.py tests/test_tray_preset_menu.py tests/test_run_script.py tests/test_install_script.py tests/test_verify_script.py -q
```

- [ ] **Step 2: Inspect the package diff**

```bash
git diff --check origin/main...HEAD
git diff --stat origin/main...HEAD
git status --short
```

Expected: no whitespace errors, only planned source/tests/docs changes, and no secret-bearing files.

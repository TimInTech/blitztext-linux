# Blitztext Linux Roadmap

This roadmap describes the Linux-focused direction of the repository.
It is a planning note, not a promise.

## Current scope

- Linux desktop app for Ubuntu/Kubuntu on KDE Plasma and Wayland
- PyQt6 tray application with a real window fallback
- Global hotkeys via `evdev`
- Local transcription via `openai-whisper` and optional `faster-whisper`
- Optional OpenAI rewriting workflows
- Diktat, Verlauf, Vorlesen, and notifications
- Install / verify / autostart flow driven by `scripts/install.sh` and `scripts/verify.sh`

## Next useful work

- Keep the Linux README and `docs/` tree aligned with the actual app behavior
- Tighten CI coverage for repo-root docs and scripts
- Reduce stale local artifacts and improve repo hygiene
- Improve the X11 fallback story or document the Wayland-only limitations more clearly
- Keep the installer and verify script in sync with the dependencies they check
- Add more regression coverage around startup, config, and transcription edge cases
- Replace the current `evdev`/`input` global-hotkey path with a desktop-native XDG GlobalShortcuts integration when it is practical for KDE/Wayland
- Add a lightweight launch smoke test (boot the app offscreen and exit cleanly) so CI confirms the GUI actually starts, not just that mocked logic passes
- Export transcribed text as a shareable audio file (e.g. OGG/Opus or MP3) so longer transcripts can be sent as a voice message via WhatsApp or similar (builds on the TTS pipeline)

## Paket H — Audit hardening (2026-06-21)

Derived from an external code audit, cross-verified by three independent
reviews (Claude, `security-reviewer`, Codex). Verdict: neither of the two
findings flagged "critical" is actually critical for this single-user,
no-network desktop app. The items below are real-but-lower-severity hardening
and quality improvements, ordered for step-by-step execution.

Phase 1 — worthwhile hardening (recommended):

- [x] H1 `config.py` `_load()`: split the broad `except Exception` (lines
      ~115-117) into `json.JSONDecodeError` and `PermissionError`/`OSError`,
      each logged with `exc_info=True` so failures are debuggable. (MEDIUM)
- [x] H2 `run.sh` secrets sourcing (lines ~24-30): add an ownership/permission
      check before `source` (`[[ -O "$SECRETS_FILE" ]]` + warn if perms are
      looser than 600); keep `source`. Do NOT use the audit's
      `export $(grep ... | xargs)` fix — it corrupts keys with spaces/special
      chars via word-splitting. (MEDIUM, defense-in-depth)

Phase 2 — optional cleanups (LOW):

- [x] H3 `transcribe.py` (line ~62): `Path(wav_file).resolve()` as
      defense-in-depth (no real traversal vector exists; path is app-generated).
- [x] H4 `llm_service.py`: replace the `MagicMock` production fallback with a
      small `_NullLLMClient` stub so `unittest.mock` is not on the prod path.
- [ ] H5 `hotkey_service.py` (line ~319): optional short `time.sleep` after the
      inner `break` as cheap insurance (no real busy-loop — `select(...,1.0)`
      and fd-pop already prevent CPU spin). Deferred intentionally: optional only,
      no reproduced bug and no strong red test yet.

Phase 3 — only if desired / verify first:

- [x] H6 Make `PasteService` key delay configurable via config and wire it through app init/runtime updates.
- [x] H7 `transcribe._transcribe_openai`: avoid leaking `CUDA_VISIBLE_DEVICES`
      mutations beyond the OpenAI Whisper call; local override restored after use.
- [x] H8 Collapse the duplicate default model source (`llm_service.MODEL` vs
      `config.py` default) to a single source of truth.
- [x] H9 Verify (do not blindly remove) the `tts_openai_voice` validation set:
      "marin"/"cedar" appear to be real newer OpenAI voices — the audit is
      likely wrong here. Verified against the installed OpenAI client; no code
      change needed.

Explicitly out: treating finding 2 (path traversal) as critical; adopting the
audit's flawed `run.sh` xargs fix.

## Not in scope

- Hosted backend services
- App Store distribution
- macOS-first feature work
- Secrets management outside the local config file and user-controlled OpenAI account

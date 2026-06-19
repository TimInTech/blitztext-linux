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

## Not in scope

- Hosted backend services
- App Store distribution
- macOS-first feature work
- Secrets management outside the local config file and user-controlled OpenAI account

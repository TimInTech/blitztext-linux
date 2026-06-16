# Security Policy

Blitztext Linux is experimental software.

It is provided as-is, without warranty, support guarantees, or production-readiness claims.

## Supported Versions

Only the current `main` branch is considered for security fixes.

## Reporting A Vulnerability

Please do not open a public issue with sensitive security details.

Use GitHub private vulnerability reporting for this repository. Maintainers should enable it before making the repository public.

If private vulnerability reporting is not available yet, open a minimal public issue titled `Security contact request` without technical details.

Do not include OpenAI API keys, access tokens, private recordings, or confidential transcripts in a report.

Include:

- what you found
- how to reproduce it
- what data or system access could be affected
- your suggested fix, if you have one

## Security Notes

- The app sends audio and text directly to OpenAI when you use the remote workflows.
- Your OpenAI API key is stored in `~/.config/blitztext-linux/config.json`, written with restrictive `0o600` permissions.
- Temporary audio files may exist briefly during processing.
- Auto-paste uses `ydotool` to inject `Ctrl+V` into the focused application.
- Global hotkeys read input from `/dev/input/event*` via `evdev`, which requires membership in the `input` group. On a shared session this means other processes of the same user could read input as well — a deliberate trade-off under Wayland without XDG GlobalShortcuts. Run Blitztext only in environments you trust. Replacing this path with a desktop-native XDG GlobalShortcuts integration is on the roadmap.

Do not use this software for confidential or regulated data without your own review.

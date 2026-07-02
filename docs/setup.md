# Setup Reference

This document is the legacy setup note for the Blitztext repository.
The current Linux install path is the one in `README.md`:

```bash
bash scripts/install.sh
```

## After installation

1. Restart or log out and back in so the `input` group is active.
2. Run the verification script:

   ```bash
   bash scripts/verify.sh
   ```

3. Start the app manually:

   ```bash
   ./run.sh
   ```

4. Enable autostart if you want it on every login:

   ```bash
   systemctl --user start blitztext-linux
   ```

<details>
<summary><b>Autostart wieder deaktivieren</b></summary>

```bash
systemctl --user stop blitztext-linux
systemctl --user disable blitztext-linux
```
</details>

## Desktop session notes

BlitztextLinux is developed for KDE Plasma on Wayland, with X11 fallbacks where the
underlying tools support them.

- GUI startup needs a real desktop session: either a usable `WAYLAND_DISPLAY` socket
  or `DISPLAY` must be available. In headless shells, `scripts/verify.sh` can report
  a warning even when the installed dependencies are otherwise correct.
- Qt prefers Wayland when `WAYLAND_DISPLAY` points to an existing socket. If that
  variable is stale but `DISPLAY` is set, the launcher falls back to X11.
- Clipboard support uses `wl-copy`/`wl-paste` on Wayland and `xclip` on X11.
- Auto-paste uses `ydotool`; terminal windows may need `Ctrl+Shift+V` instead of
  `Ctrl+V`, so the app detects known terminal window classes when possible.
- Global hotkeys still use `evdev`/the `input` group. A future desktop-native XDG
  GlobalShortcuts integration would be a larger replacement, not a small setup fix.

## Manual install

If you want to debug the Linux setup path step by step:

**1. System packages**

```bash
sudo apt install pulseaudio-utils wl-clipboard xclip ydotool ffmpeg python3-venv python3-evdev build-essential python3-dev socat pipx
```

| Paket | Zweck |
| :--- | :--- |
| `pulseaudio-utils` | `parec` for audio capture via PulseAudio/PipeWire |
| `wl-clipboard` / `xclip` | Clipboard support under Wayland (`wl-copy`) and X11 fallback |
| `ydotool` | Simulates `Ctrl+V` for auto-paste |
| `ffmpeg` | Audio conversion |
| `python3-evdev` | Input-device access for the global hotkey daemon |
| `socat` | Optional socket communication |
| `pipx` | Isolated installation of Whisper engines |

**2. Grant evdev access**

```bash
sudo usermod -aG input $USER
```

**3. Virtual environment and Python packages**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install PyQt6 evdev openai pytest openai-whisper faster-whisper
```

**4. Whisper engine via pipx**

If you want to install `openai-whisper` outside the venv:

```bash
pipx install --python "$(command -v python3.11)" openai-whisper
pipx inject openai-whisper faster-whisper   # optional
```

**5. Start ydotool**

```bash
systemctl --user start ydotool.service
```

**6. Launch the app**

```bash
./run.sh
```

## Troubleshooting

- If `xcodebuild` or XcodeGen appears in your notes, you are looking at an old macOS document.
- If install or runtime checks fail, start with `bash scripts/verify.sh`.
- If hotkeys do not trigger, confirm the `input` group membership and restart your session.
- If auto-paste fails but transcription works, check `ydotool.service`, clipboard tooling, and the active desktop session.

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

## Compatibility matrix (diagnostic, not a support promise)

BlitztextLinux is developed and tested on **Kubuntu (KDE Plasma, Wayland)**.
The systems below share the Ubuntu/Debian package base, so `install.sh` runs on
them, but only Kubuntu is systematically tested. This table documents expected
behavior and known risks — it is **not** an official support statement.

| Target system | Expected session | Main risks | Status |
| :--- | :--- | :--- | :--- |
| Kubuntu 26.04, Plasma | Wayland | ydotool ≥ 1.0 via apt available; lowest risk | tested |
| Ubuntu 24.04, GNOME | Wayland | apt ydotool 0.1.x is client-only → no auto-paste (clipboard mode works); GNOME tray needs the AppIndicator extension | untested |
| Ubuntu 26.04, GNOME | Wayland | GNOME tray needs the AppIndicator extension; Python 3.13/3.14: torch/openai-whisper wheels may lag behind new Python releases | untested |
| Linux Mint 22.x, Cinnamon | X11 (default) | `xclip` is the required clipboard backend, not `wl-copy`; apt ydotool 0.1.x → no auto-paste | untested |
| Lubuntu 24.04, LXQt | X11 (default) | same as Mint: `xclip` required; Qt tray via StatusNotifier usually fine | untested |
| Lubuntu 26.04, LXQt | X11 or Wayland | session type decides the clipboard backend — run `scripts/verify.sh` to see which one applies | untested |

Xfce and MATE are expected to behave like the X11 rows above, but are not
tracked here.

What works everywhere, regardless of session type:

- Transcription and clipboard copy (no `ydotool`, no `input` group needed).
- Window/tray operation without global hotkeys (`install.sh` offers this mode;
  `BLITZTEXT_NO_HOTKEY=1 bash scripts/install.sh` selects it non-interactively).

What is environment-dependent:

- **Auto-paste** needs a working `ydotoold` (ydotool ≥ 1.0).
- **Global hotkeys** need evdev access via the `input` group.
- **Clipboard backend**: `wl-copy` on Wayland, `xclip` on plain X11.
  `scripts/verify.sh` prints the detected session and which backend is required.

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

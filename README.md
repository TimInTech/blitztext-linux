<div align="center">
  <img src="docs/screenshots/linux/Banner.png" alt="Blitztext Linux Banner" width="860">
  
  <h1>Blitztext Linux</h1>
  <p><strong>Your local AI voice assistant for KDE Plasma & Wayland</strong></p>

  <p>
    <a href="https://github.com/TimInTech/blitztext-linux/actions/workflows/blitztext-linux-ci.yml"><img src="https://github.com/TimInTech/blitztext-linux/actions/workflows/blitztext-linux-ci.yml/badge.svg" alt="Blitztext Linux CI"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
    <img src="https://img.shields.io/badge/Platform-Ubuntu%2FKubuntu%20%2B%20KDE%20Plasma-blue" alt="Platform">
  </p>
  <p><strong>🇬🇧 English</strong> | <a href="README.de.md">🇩🇪 Deutsch</a></p>
  <p><i>Record speech via hotkey, transcribe locally or online, optionally rewrite it with an LLM, and paste it directly into the active application.</i></p>
</div>

> [!IMPORTANT]
> **Standalone Linux port:** This repository contains exclusively the Linux port of Blitztext – a standalone Python 3/PyQt6 implementation optimized for **Kubuntu/Ubuntu running KDE Plasma with Wayland**. For the original macOS version, please visit the [official main repository](https://github.com/cmagnussen/blitztext-app).

---

## Features

- **NEW: Multilingual interface (EN/DE):** Switch the app interface between German and English under **Settings → General → "Language"** (the change takes effect after restarting the app).
- **Custom names / terms:** Extend the AI's vocabulary with your own terms, names, or technical words for perfect transcriptions.

- **Global hotkeys:** Record from anywhere in the system at any time.
- **Auto-paste:** Detects speech and pastes it right where your cursor is.
- **LLM-powered workflows:** Let the AI rephrase your sentences professionally, filter them emotionally, or enrich them with fitting emojis.
- **Local processing:** Optionally 100% offline for full privacy.

---

## Installation

### Quick install (recommended)

The easiest way to set up Blitztext on your system:

```bash
git clone https://github.com/TimInTech/blitztext-linux.git
cd blitztext-linux
bash scripts/install.sh
```

**What does the script do?**
It is idempotent (safe to run repeatedly) and handles everything fully automatically:
1. Checks your system (Ubuntu/Debian) & Python version.
2. Installs missing system packages (incl. `pipx`).
3. Sets up a `.venv` environment and installs `openai-whisper`/`faster-whisper`.
4. Prepares `ydotool.service` and the systemd user service.

### After installation

1. **Restart required** (or log out/in) so the `input` group becomes active. Then verify:
   ```bash
   bash scripts/verify.sh
   ```
2. **Test manually:**
   ```bash
   ./run.sh
   ```
   *(Does the tray icon appear and do the hotkeys respond? Then everything went smoothly!)*
3. **Enable autostart:**
   ```bash
   systemctl --user start blitztext-linux
   ```

<details>
<summary><b>Disable autostart again</b></summary>

```bash
systemctl --user stop blitztext-linux
systemctl --user disable blitztext-linux
```
</details>

<details>
<summary><b>Manual installation (diagnostics / experts)</b></summary>

In case you want to debug specifically instead of using `scripts/install.sh`:

**1. System packages (apt)**
```bash
sudo apt install pulseaudio-utils wl-clipboard xclip ydotool ffmpeg python3-venv python3-evdev build-essential python3-dev socat pipx
```

| Package | Purpose |
| :--- | :--- |
| `pulseaudio-utils` | `parec` for audio recording via PulseAudio/PipeWire |
| `wl-clipboard` / `xclip` | Clipboard under Wayland (`wl-copy`) or X11 fallback |
| `ydotool` (≥ 1.0) | Simulates `Ctrl+V` for automatic pasting (auto-paste). From version 1.0 onward, raw keycodes are used. **Ubuntu 25.10/26.04** ship ydotool ≥ 1.0 (1.0.4) directly via `apt`. **Ubuntu 24.04 and 22.04** only ship 0.1.x via `apt` (e.g. 0.1.8), which does not support keycodes and therefore has no auto-paste – build ydotool ≥ 1.0 from source there (see below). Auto-paste verified on 24.04, 25.10, and 26.04. |
| `ffmpeg` | Audio conversions |
| `python3-evdev` | Input device access for the system-wide hotkey daemon |
| `socat` | Optional socket communication |
| `pipx` | Isolated installation of Whisper engines |

**2. Grant evdev permissions**
```bash
sudo usermod -aG input $USER
```

**3. Virtual environment & Python packages**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install PyQt6 evdev openai pytest openai-whisper faster-whisper
```

**4. Whisper engine as an alternative via pipx**
If you want to install `openai-whisper` decoupled from the venv (avoids version conflicts on newer Ubuntu setups due to Python 3.11):
```bash
pipx install --python "$(command -v python3.11)" openai-whisper
pipx inject openai-whisper faster-whisper   # optional, for accelerated execution
```

**5. Check ydotool**
```bash
systemctl --user start ydotool.service
```
If `apt` only provides ydotool 0.1.x (Ubuntu 24.04/22.04), build ydotool ≥ 1.0 from source:
```bash
sudo apt install cmake build-essential scdoc git
git clone --depth 1 --branch v1.0.4 https://github.com/ReimuNotMoe/ydotool.git
cd ydotool && cmake -B build -DCMAKE_BUILD_TYPE=Release && make -C build && sudo make -C build install
systemctl --user enable --now ydotool.service   # uses /usr/local/bin/ydotoold
```

**6. Start the application**
```bash
./run.sh
```
</details>

---

## The 5 workflows and hotkeys

Blitztext registers global hotkeys via `evdev`. With these combinations you have full control:

| Workflow | Hotkey | LLM? | Description |
| :--- | :--- | :---: | :--- |
| **Blitztext** | <kbd>Meta</kbd> + <kbd>H</kbd> | ❌ | Default: records, transcribes, and pastes the text. |
| **Blitztext Local** | <kbd>Meta</kbd> + <kbd>Shift</kbd> + <kbd>H</kbd> | ❌ | Forces a pure **offline transcription**. |
| **Blitztext+** | <kbd>Meta</kbd> + <kbd>Shift</kbd> + <kbd>T</kbd> | ✅ | Rephrases your recording professionally via LLM. |
| **Blitztext $%&!** | <kbd>Meta</kbd> + <kbd>Shift</kbd> + <kbd>D</kbd> | ✅ | Emotional release: turns frustration into a matter-of-fact message. |
| **Blitztext :)** | <kbd>Meta</kbd> + <kbd>Shift</kbd> + <kbd>E</kbd> | ✅ | Enriches your message with fitting emojis. |

> [!NOTE]
> **LLM workflows** (`Blitztext+`, `Blitztext $%&!`, `Blitztext :)`) require a valid **OpenAI API key**. The easiest way is to place it in `~/.config/blitztext-linux/secrets.env` by setting the variable `OPENAI_API_KEY` there with your key as the value (line format `NAME=VALUE`). `./run.sh` and the systemd service load this file automatically. Without this key, these functions are disabled in the menu and via the hotkeys, or result in an error message.

## AI workflows

The AI workflows help with phrasing, tone, and emojis. You'll find the relevant settings directly in the app:

<div align="center">
  <img src="docs/screenshots/linux/settings-ki-workflows.png" alt="AI workflow settings" width="480">
  <br><br>
</div>

### Writing-style presets

For the **Blitztext+** workflow (text improver) there are ready-made writing-style presets that you select under **Settings → AI Workflows → "Writing-style preset"**:

| Preset | Effect |
| --- | --- |
| **Standard (improve text)** | Previous behavior – cleanly formatted text, the selected **tone** applies. |
| **Email – formal** | Polite email in the formal form with a clear structure. |
| **Email – casual** | Friendly email in the informal form. |
| **Bullet points** | Structures the content into concise bullet points. |
| **Summary** | Concise, factual summary of the key statements. |
| **Personal (informal)** | Clear text in a personal, informal tone. |
| **Polite (formal)** | Clear text in a polite, formal tone. |
| **Short & precise** | As concise as possible, without filler words and repetitions. |

> With **Standard**, the configured **tone** is additionally applied. Every other preset brings its own writing style and replaces the tone. Custom names/terms are preserved in all presets.

---

## Tray icon: status colors

The microphone in the system tray is your indicator of the current state:

<div align="center">
  <table>
    <tr>
      <td align="center" width="25%">
        <img src="docs/screenshots/linux/tray-idle.png" width="60"><br><br>
        <b>Green</b> (IDLE)<br>
        <i>Ready — waiting for your action.</i>
      </td>
      <td align="center" width="25%">
        <img src="docs/screenshots/linux/tray-recording.png" width="60"><br><br>
        <b>Red</b> (RECORDING)<br>
        <i>Recording is actively running.</i>
      </td>
      <td align="center" width="25%">
        <img src="docs/screenshots/linux/tray-processing.png" width="60"><br><br>
        <b>Orange</b> (TRANSCRIBING)<br>
        <i>Magic in progress (transcription / AI rephrasing).</i>
      </td>
      <td align="center" width="25%">
        <img src="docs/screenshots/linux/tray-error.png" width="60"><br><br>
        <b>Gray</b> (ERROR)<br>
        <i>Oops, something went wrong.</i>
      </td>
    </tr>
  </table>
</div>

> [!NOTE]
> If no tray area is available in the desktop environment, the icon falls back to the system theme `audio-input-microphone`; the color coding may then not apply.

---

## Main window (graphical fallback)

In case you don't have a keyboard handy or hotkeys are blocked:

<div align="center">
  <br>
  <img src="docs/screenshots/linux/main-window-compact-glass.png" alt="Main window" width="480">
  <br><br>
</div>

- **Mouse control:** Start/stop button for recording.
- **Workflow menu:** Dropdown for all 5 modes.
- **Cancel:** Discards a recording immediately without transcription.
- **Quick access:** Dictation, history, read-aloud, and settings.

*The window opens at startup as well as via the tray entry **Show window** or a click on the tray icon. Closing only hides the window — the app keeps running in the tray.*

---

## Dictation, history, and read-aloud

In addition to the workflows, the tool offers three convenience functions:

<div align="center">
  <br>
  <img src="docs/screenshots/linux/history.png" alt="History" width="340">
  <img src="docs/screenshots/linux/tts.png" alt="Read aloud" width="340">
  <br><br>
</div>

| Menu item | Description |
| :--- | :--- |
| **Dictation mode** | Toggle. When active, all transcripts are collected as dictation entries and each saved as a Markdown file. The history then shows a **Merge** button that combines all entries and copies them to the clipboard. |
| **History…** | Opens a window with the most recent transcripts. Per entry: copy to clipboard or delete. |
| **Read aloud…** | Reads any text aloud to you — locally via **Piper TTS** (default) or optionally via **OpenAI Cloud TTS** (including provider, voice, and model selection)! |

> [!NOTE]
> **Dictation notes** are written exclusively into a folder **inside the home directory** (protection against path traversal), with permissions `0o600`.

> [!IMPORTANT]
> **Piper TTS** must be installed for the read-aloud function (as well as voices):
> ```bash
> .venv/bin/pip install piper-tts
> # Place voices (.onnx + .onnx.json) into ~/.local/share/piper-voices/
> ```
> If Piper or a voice is missing, the read-aloud window shows an installation hint; all other functions remain usable. Optional desktop notifications use `notify-send` (package `libnotify-bin`).

> [!NOTE]
> **OpenAI Cloud TTS** is an optional alternative to Piper. Requirements: the `openai` package (`.venv/bin/pip install openai`) and a valid key in the environment variable `OPENAI_API_KEY` (see `secrets.env` below). When first switching to the "OpenAI Cloud" provider, the read-aloud window asks for confirmation once, because the entered text is sent to OpenAI's servers for synthesis. Piper remains the default and works entirely locally.

---

## Configuration

Everything is stored locally and securely under `~/.config/blitztext-linux/config.json`. The OpenAI key is no longer stored in this file but read from an environment variable. The configuration file can be opened directly from the settings for advanced prompt and workflow adjustments: **Settings → General → "Open configuration file"**.

<div align="center">
  <img src="docs/screenshots/linux/settings-allgemein.png" alt="General settings" width="480">
  <br><br>
</div>

> [!IMPORTANT]
> The configuration file is automatically saved with restrictive file permissions (**`0o600` / `chmod 600`**). The real OpenAI key instead lives in `~/.config/blitztext-linux/secrets.env` or is provided as an environment variable.

<details>
<summary><b>Example configuration & field explanation</b></summary>

```json
{
  "model": "base",
  "language": "de",
  "ui_language": "de",
  "backend": "openai-whisper",
  "hotkey_mode": "toggle",
  "openai_api_key_env": "OPENAI_API_KEY",
  "autopaste": true,
  "audio_device": "@DEFAULT_SOURCE@",
  "workflows": {
    "text_improver_tone": "neutral",
    "emoji_density": "mittel",
    "dampf_system_prompt": ""
  }
}
```

- **model**: Whisper model size (`tiny`, `base`, `small`, `medium`, `large`, `large-v2`, `large-v3`, `large-v3-turbo`). Default: `base`.
- **language**: Transcription language (`de`, `en`) or `auto`.
- **ui_language**: Language of the app interface (`de` or `en`). Default: `de`. Changes take effect after a restart.
- **backend**: `openai-whisper` or `faster-whisper`.
- **hotkey_mode**: 
  - `toggle`: press once to start, press again to stop.
  - `hold`: recording runs as long as the hotkey is held.
- **openai_api_key_env**: Name of the environment variable for the OpenAI API key. Default: `OPENAI_API_KEY`.
- The actual key does not live in `config.json` but in `~/.config/blitztext-linux/secrets.env` or an already-set environment variable.
- **autopaste**: Pastes via `ydotool`.
- **audio_device**: Name of the audio source.
- **tts_provider**: TTS provider for "Read aloud" — `piper` (local, default) or `openai` (cloud).
- **tts_openai_model** / **tts_openai_voice**: Model and voice for OpenAI Cloud TTS (default: `gpt-4o-mini-tts`, `marin`).
- **tts_openai_consent**: `true` once the one-time privacy confirmation for Cloud TTS has been granted. Default: `false`.
- **workflows**: Fine-tuning of tonality (`text_improver_tone`), writing-style preset (`writing_preset`), emojis (`emoji_density`), and the steam-release prompt (`dampf_system_prompt`).
</details>

---

## Development and tests

We love stability! Run the tests locally:

```bash
pytest
```

With `WHISPER_GUI_TESTS=1 QT_QPA_PLATFORM=offscreen pytest`, the GUI tests of the main window run additionally.

<details>
<summary><b>Directory overview</b></summary>

```text
.
├── app/
│   ├── __init__.py
│   ├── audio_recorder.py   # PulseAudio/PipeWire recording via parec
│   ├── blitztext_linux.py  # PyQt6 main application (system tray)
│   ├── config.py           # Configuration manager
│   ├── hotkey_service.py   # evdev-based hotkey daemon
│   ├── i18n.py             # Interface translations (DE/EN)
│   ├── llm_service.py      # OpenAI API interface
│   ├── paste_service.py    # Wayland clipboard integration
│   ├── transcribe.py       # Whisper transcription
│   └── workflows.py        # Workflow definitions
├── tests/                  # Test suite
└── README.md               # This document (German version: README.de.md)
```
</details>

---

## Important notes

- **Linux exclusive:** For Linux systems only.
- **Wayland focus:** Developed for Wayland (`wl-clipboard`, `ydotool`).
- **Privacy:** Local workflows stay 100% on your machine. OpenAI is only contacted when needed for LLM tasks.
- **Security (`evdev` & `input` group):** The tool reads input globally via `/dev/input/event*`. At the system level, this means all of the user's processes could read along with input (a trade-off under Wayland without XDG GlobalShortcuts). Only use Blitztext in environments you trust!
- **Developer note:** This project was designed with the support of artificial intelligence (AI-assisted). Architecture, code, and tests were reviewed manually and verified locally for function/security.

---

## Legal / Imprint & privacy (original project)

This project is a Linux port of the macOS application "Blitztext". For fairness and correct attribution, we refer to the legal information of the original project:

The original project is an experimental, non-commercial open-source project under the MIT license. The associated website ([blitztext.de](https://blitztext.de/)) is operated by Blackboat Internet GmbH:

- Imprint: https://www.blackboat.com/impressum
- Privacy: https://www.blackboat.com/datenschutz

---

<div align="center">
  <sub>Made with ❤️ (and a little AI help).</sub>
</div>

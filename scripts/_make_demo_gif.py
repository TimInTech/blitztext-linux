"""Generate the animated README demo GIF for Blitztext Linux.

The GIF shows the real product: the actual PyQt6 main window is rendered
offscreen and grabbed in its true states (ready → recording → transcribing →
ready), exactly like ``scripts/_make_screenshots.py`` does for the static
README screenshots. Next to it, a plain target text field receives the
transcript. The real tray icons from ``docs/screenshots/linux`` mirror the
workflow states. No invented controls are drawn.

The displayed hotkey matches the actual default configuration: the standard
Blitztext workflow (``WorkflowType.TRANSCRIPTION``) is triggered by holding
the left Alt key (``transcription_hotkey: KEY_LEFTALT``, ``hotkey_mode:
hold`` — see ``app/config.py`` and ``_HOTKEY_MAP`` in
``app/hotkey_service.py``).

Usage:
    PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/_make_demo_gif.py [out_dir]

Default output directory:
    docs/screenshots/linux  (writes demo-en.gif and demo-de.gif)
"""
from __future__ import annotations

import os
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont

SCREENSHOT_DIR = Path("docs/screenshots/linux")
CANVAS_SIZE = (960, 540)
BACKGROUND_TOP = (7, 17, 31)
BACKGROUND_BOTTOM = (2, 6, 13)
ACCENT = "#2db2ff"
FIELD_BG = (18, 28, 44, 255)
FIELD_BORDER = (50, 127, 194, 160)
PANEL_BG = (9, 15, 26, 255)
TEXT_PRIMARY = "#eef6ff"
TEXT_SECONDARY = "#8ea6c1"
IDLE_GREEN = "#4ade80"

APP_WINDOW_SCALE = 1.5
APP_WINDOW_POS = (64, 84)
FIELD_BOX = (500, 108, 900, 420)
TYPE_CHUNK = 3
TYPE_FRAME_MS = 45

LANG_COPY = {
    "en": {
        "gif": "demo-en.gif",
        "field_caption": "Active application",
        "hint": "Hold  Alt  and speak",
        "hotkey": "Alt",
        "hotkey_sub": "hold",
        "spoken": "“Hi Anna, I’ll send you the updated rollout plan right after our meeting.”",
        "typed": "Hi Anna, I’ll send you the updated rollout plan right after our meeting.",
        "badge": "✓ Pasted — transcribed 100% locally",
    },
    "de": {
        "gif": "demo-de.gif",
        "field_caption": "Aktive Anwendung",
        "hint": "Alt  gedrückt halten und sprechen",
        "hotkey": "Alt",
        "hotkey_sub": "gedrückt halten",
        "spoken": "„Hallo Anna, ich schicke dir den aktualisierten Rollout-Plan direkt nach unserem Meeting.“",
        "typed": "Hallo Anna, ich schicke dir den aktualisierten Rollout-Plan direkt nach unserem Meeting.",
        "badge": "✓ Eingefügt — 100 % lokal transkribiert",
    },
}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


FONT_BODY = _font(19)
FONT_CAPTION = _font(15, bold=True)
FONT_HINT = _font(22, bold=True)
FONT_CHIP = _font(30, bold=True)
FONT_CHIP_SUB = _font(15)
FONT_SUBTITLE = _font(18)
FONT_BADGE = _font(17, bold=True)
FONT_CLOCK = _font(15)


def _typewriter_chunks(text: str, chunk: int = TYPE_CHUNK) -> list[str]:
    """Progressive prefixes of ``text`` for the typing animation.

    The last element is always the full text; an empty input yields no frames.
    """
    if not text:
        return []
    if chunk < 1:
        raise ValueError(f"chunk must be >= 1, got {chunk}")
    prefixes = [text[:end] for end in range(chunk, len(text), chunk)]
    prefixes.append(text)
    return prefixes


def _wrap_lines(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> list[str]:
    """Word-wrap ``text`` so every rendered line fits into ``width`` pixels."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _load_tray_icon(name: str, size: int = 30) -> Image.Image:
    path = SCREENSHOT_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"Tray icon missing for demo GIF: {path}")
    icon = Image.open(path).convert("RGBA")
    icon.thumbnail((size, size), Image.Resampling.LANCZOS)
    return icon


def _scale_app_window(image: Image.Image, scale: float = APP_WINDOW_SCALE) -> Image.Image:
    size = (round(image.width * scale), round(image.height * scale))
    return image.resize(size, Image.Resampling.LANCZOS)


@lru_cache(maxsize=1)
def _background() -> Image.Image:
    bg = Image.new("RGBA", CANVAS_SIZE)
    draw = ImageDraw.Draw(bg)
    for y in range(CANVAS_SIZE[1]):
        ratio = y / max(1, CANVAS_SIZE[1] - 1)
        color = tuple(
            int(BACKGROUND_TOP[i] * (1 - ratio) + BACKGROUND_BOTTOM[i] * ratio)
            for i in range(3)
        )
        draw.line((0, y, CANVAS_SIZE[0], y), fill=color + (255,))
    return bg


def _draw_target_field(draw: ImageDraw.ImageDraw, copy: dict, typed: str, cursor_on: bool) -> None:
    x0, y0, x1, y1 = FIELD_BOX
    draw.text((x0, y0 - 26), copy["field_caption"], font=FONT_CAPTION, fill=TEXT_SECONDARY)
    draw.rounded_rectangle(FIELD_BOX, radius=10, fill=FIELD_BG, outline=FIELD_BORDER, width=2)
    lines = _wrap_lines(draw, typed, FONT_BODY, x1 - x0 - 48) if typed else []
    x, y = x0 + 24, y0 + 22
    line_height = FONT_BODY.size + 9
    for line in lines:
        draw.text((x, y), line, font=FONT_BODY, fill=TEXT_PRIMARY)
        y += line_height
    if cursor_on:
        cursor_x = x + (draw.textlength(lines[-1], font=FONT_BODY) + 4 if lines else 0)
        cursor_y = y - line_height if lines else y
        draw.line((cursor_x, cursor_y + 2, cursor_x, cursor_y + FONT_BODY.size + 4), fill=ACCENT, width=2)


def _draw_panel(canvas: Image.Image, draw: ImageDraw.ImageDraw, tray_icon: Image.Image) -> None:
    draw.rectangle((0, 496, CANVAS_SIZE[0], CANVAS_SIZE[1]), fill=PANEL_BG)
    draw.line((0, 496, CANVAS_SIZE[0], 496), fill=(50, 127, 194, 120), width=1)
    icon_x = CANVAS_SIZE[0] - 108
    icon_y = 496 + (44 - tray_icon.height) // 2
    canvas.alpha_composite(tray_icon, (icon_x, icon_y))
    draw.text((CANVAS_SIZE[0] - 62, 510), "14:32", font=FONT_CLOCK, fill=TEXT_SECONDARY)


def _draw_hint(draw: ImageDraw.ImageDraw, text: str) -> None:
    width = draw.textlength(text, font=FONT_HINT)
    x0, y0, x1, _ = FIELD_BOX
    cx = (x0 + x1) / 2
    x = cx - width / 2
    draw.rounded_rectangle((x - 22, y0 + 108, x + width + 22, y0 + 162), radius=14, fill=(10, 22, 39, 235), outline=FIELD_BORDER, width=2)
    draw.text((x, y0 + 122), text, font=FONT_HINT, fill=TEXT_PRIMARY)


def _draw_hotkey_chip(draw: ImageDraw.ImageDraw, copy: dict) -> None:
    x0, y0, x1, _ = FIELD_BOX
    cx = (x0 + x1) / 2
    key_w = draw.textlength(copy["hotkey"], font=FONT_CHIP)
    sub_w = draw.textlength(copy["hotkey_sub"], font=FONT_CHIP_SUB)
    box_w = max(key_w, sub_w) + 64
    draw.rounded_rectangle((cx - box_w / 2, y0 + 96, cx + box_w / 2, y0 + 186), radius=16, fill=(13, 60, 105, 245), outline=ACCENT, width=3)
    draw.text((cx - key_w / 2, y0 + 112), copy["hotkey"], font=FONT_CHIP, fill=TEXT_PRIMARY)
    draw.text((cx - sub_w / 2, y0 + 154), copy["hotkey_sub"], font=FONT_CHIP_SUB, fill=TEXT_SECONDARY)


def _draw_subtitle(draw: ImageDraw.ImageDraw, text: str) -> None:
    lines = _wrap_lines(draw, text, FONT_SUBTITLE, 780)
    y = 444
    for line in lines:
        draw.text((CANVAS_SIZE[0] / 2, y), line, font=FONT_SUBTITLE, fill=TEXT_SECONDARY, anchor="ma")
        y += FONT_SUBTITLE.size + 6


def _draw_badge(draw: ImageDraw.ImageDraw, text: str) -> None:
    width = draw.textlength(text, font=FONT_BADGE)
    x0, y0, x1, y1 = FIELD_BOX
    cx = (x0 + x1) / 2
    x = cx - width / 2
    draw.rounded_rectangle((x - 20, y1 + 14, x + width + 20, y1 + 50), radius=12, fill=(9, 48, 30, 240), outline=(74, 222, 128, 220), width=2)
    draw.text((x, y1 + 22), text, font=FONT_BADGE, fill=IDLE_GREEN)


def _scene(
    copy: dict,
    icons: dict[str, Image.Image],
    app_states: dict[str, Image.Image],
    *,
    app_state: str = "idle",
    tray: str = "idle",
    typed: str = "",
    cursor_on: bool = True,
    hint: bool = False,
    hotkey: bool = False,
    subtitle: bool = False,
    badge: bool = False,
) -> Image.Image:
    canvas = _background().copy()
    canvas.alpha_composite(app_states[app_state], APP_WINDOW_POS)
    draw = ImageDraw.Draw(canvas)
    _draw_target_field(draw, copy, typed, cursor_on)
    _draw_panel(canvas, draw, icons[tray])
    if hint:
        _draw_hint(draw, copy["hint"])
    if hotkey:
        _draw_hotkey_chip(draw, copy)
    if subtitle:
        _draw_subtitle(draw, copy["spoken"])
    if badge:
        _draw_badge(draw, copy["badge"])
    return canvas


def _build_frames(
    lang: str,
    icons: dict[str, Image.Image],
    app_states: dict[str, Image.Image],
) -> list[tuple[Image.Image, int]]:
    """All GIF frames with per-frame durations (ms) for one language."""
    copy = LANG_COPY[lang]
    frames: list[tuple[Image.Image, int]] = []

    def scene(**kwargs) -> Image.Image:
        return _scene(copy, icons, app_states, **kwargs)

    # 1. Ready: real IDLE window, blinking cursor in the target field, hint
    for cursor_on, duration in ((True, 650), (False, 420), (True, 650)):
        frames.append((scene(hint=True, cursor_on=cursor_on), duration))

    # 2. Hotkey held (real default: hold left Alt, see module docstring)
    frames.append((scene(hotkey=True), 950))

    # 3. Recording: real RECORDING window, timer counting up, spoken sentence
    for state in ("recording-1", "recording-2", "recording-3"):
        frames.append((scene(app_state=state, tray="recording", subtitle=True, cursor_on=False), 700))

    # 4. Transcribing: real TRANSCRIBING window
    for duration in (500, 500, 400):
        frames.append((scene(app_state="transcribing", tray="processing", cursor_on=False), duration))

    # 5. Typing: transcript lands in the target field, window back to ready
    for prefix in _typewriter_chunks(copy["typed"]):
        frames.append((scene(typed=prefix), TYPE_FRAME_MS))

    # 6. Final hold with badge
    frames.append((scene(typed=copy["typed"]), 700))
    frames.append((scene(typed=copy["typed"], badge=True), 3200))
    return frames


def _save_gif(frames: list[tuple[Image.Image, int]], path: Path) -> None:
    if not frames:
        raise ValueError("Cannot write GIF without frames")
    images = [frame.convert("RGB").quantize(colors=256, dither=Image.Dither.NONE) for frame, _ in frames]
    durations = [duration for _, duration in frames]
    images[0].save(
        str(path),
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )


def _grab_app_states(lang: str) -> dict[str, Image.Image]:
    """Grab the real main window offscreen in its true workflow states.

    Mirrors the approach of ``scripts/_make_screenshots.py``: the actual
    ``MainWindow`` widget is instantiated with a no-op controller, driven
    through ``update_state`` and grabbed per state. The default workflow
    (Blitztext / TRANSCRIPTION) stays selected, matching the Alt hotkey shown
    in the demo.
    """
    from PyQt6.QtWidgets import QApplication

    from app import theme
    from app.i18n import set_language
    from app.main_window import MainWindow

    app = QApplication.instance()
    assert app is not None, "QApplication must exist before grabbing app states"

    # Wie im echten App-Start (blitztext_linux.main): Breeze-Dark-Glass-Theme.
    theme.apply_theme(app)
    set_language(lang)
    controller = SimpleNamespace(
        gui_toggle_recording=lambda *a, **k: None,
        gui_discard=lambda *a, **k: None,
        set_dictation_mode=lambda *a, **k: None,
        show_history_panel=lambda *a, **k: None,
        show_settings_dialog=lambda *a, **k: None,
        show_tts_window=lambda *a, **k: None,
        main_window_preset_changed=lambda *a, **k: None,
    )
    window = MainWindow(controller)
    window.show()

    def grab(state: str, timer_text: str | None = None) -> Image.Image:
        window.update_state(state, None, None)
        if timer_text is not None:
            window._timer_label.setText(timer_text)
        for _ in range(10):
            app.processEvents()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            tmp = Path(handle.name)
        try:
            window.grab().save(str(tmp))
            image = Image.open(tmp).convert("RGBA")
            image.load()
        finally:
            tmp.unlink(missing_ok=True)
        return _scale_app_window(image)

    states = {
        "idle": grab("IDLE"),
        "recording-1": grab("RECORDING", "00:01"),
        "recording-2": grab("RECORDING", "00:02"),
        "recording-3": grab("RECORDING", "00:03"),
        "transcribing": grab("TRANSCRIBING"),
    }
    window.close()
    return states


def main() -> int:
    from PyQt6.QtWidgets import QApplication

    out_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else SCREENSHOT_DIR.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    qt_app = QApplication(sys.argv)  # noqa: F841 — Referenz hält die QApplication am Leben
    icons = {
        "idle": _load_tray_icon("tray-idle.png"),
        "recording": _load_tray_icon("tray-recording.png"),
        "processing": _load_tray_icon("tray-processing.png"),
    }
    for lang in ("en", "de"):
        copy = LANG_COPY[lang]
        app_states = _grab_app_states(lang)
        frames = _build_frames(lang, icons, app_states)
        out_path = out_dir / copy["gif"]
        _save_gif(frames, out_path)
        size_kb = out_path.stat().st_size / 1024
        print(f"  ✓ {out_path.name} ({len(frames)} frames, {size_kb:.0f} KiB)")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

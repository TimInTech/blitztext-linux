"""Generate README screenshots and banner assets for Blitztext Linux.

The script renders the current PyQt6 widgets offscreen and builds language-specific
banner images from real UI screenshots.

Usage:
    PYTHONPATH=. QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/_make_screenshots.py [out_dir]

Default output directory:
    docs/screenshots/linux
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtWidgets import QApplication

from app import theme
from app.blitztext_linux import BlitztextApp, Config, SettingsDialog
from app.compose_window import ComposeWindow
from app.config import BlitztextConfig
from app.history_panel import HistoryPanel
from app.i18n import set_language, t, tq
from app.llm_service import LLMService, WorkflowType
from app.main_window import MainWindow
from app.paste_service import PasteService
from app.tts_window import TtsWindow

SCREENSHOT_DIR = Path("docs/screenshots/linux")
CANVAS_SIZE = (1280, 640)
BACKGROUND_TOP = "#07111f"
BACKGROUND_BOTTOM = "#02060d"
ACCENT = "#2db2ff"
CARD_BG = (14, 24, 38, 214)
CARD_BORDER = (50, 127, 194, 140)
TEXT_PRIMARY = "#eef6ff"
TEXT_SECONDARY = "#8ea6c1"
LABEL_BG = (37, 174, 255, 220)

LANG_COPY = {
    "en": {
        "banner": "Banner-en.png",
        "hero": "Your local AI voice assistant for Linux",
        "sub": "Record speech, transcribe locally or online, optionally rewrite it with AI, and paste it directly into the active app.",
        "flow": "Record  •  Transcribe  •  Rewrite  •  Paste",
        "feature_title": "Current highlights",
        "tag_new": "NEW",
        "chips": [
            ("Compose window", "Draft, refine and compare AI-rewritten text before pasting it anywhere."),
            ("Single-panel widget", "Unified frameless surface with gold microphone, waves and tool row."),
            ("Tone & template control", "Choose tone and writing template directly inside the Compose window."),
            ("Prompt transparency", "Inspect and edit the AI system prompt before running a rewrite."),
        ],
        "labels": {
            "main": "Main window",
            "compose": "Compose window",
            "workflows": "Settings → AI Workflows",
            "tray": "Tray presets",
        },
        "compose_input": "Please help me write a concise follow-up email for our product meeting earlier today.",
        "compose_output": "Hi team,\n\nThank you for the productive discussion today. Here are the key action items we agreed on:\n\n• Finalise the API contract by Friday\n• Schedule a follow-up review for next Tuesday\n• Share the updated roadmap with stakeholders\n\nLet me know if I missed anything.\n\nBest,",
        "custom_prompt": "Write a friendly and concise message. Keep all key action items direct.",
        "history_entries": [
            ("Please move tomorrow's team sync to 10:00.", False),
            ("Could you send me the updated rollout plan afterwards?", True),
            ("The draft is ready and stored in the shared project folder.", False),
        ],
        "tts_text": "Read this short summary aloud with the current voice settings.",
        "tts_voice": "en_US-amy-medium",
    },
    "de": {
        "banner": "Banner-de.png",
        "hero": "Dein lokaler KI-Sprachassistent für Linux",
        "sub": "Sprache aufnehmen, lokal oder online transkribieren, optional mit KI umformulieren und direkt in die aktive Anwendung einfügen.",
        "flow": "Aufnehmen • Transkribieren • Umschreiben • Einfügen",
        "feature_title": "Aktuelle Highlights",
        "tag_new": "NEU",
        "chips": [
            ("Entwurfsfenster", "Text entwerfen, verfeinern und KI-Varianten vergleichen, bevor du einfügst."),
            ("Single-Panel-Widget", "Kompakte rahmenlose Einzelfläche mit Gold-Mikrofon, Wellen und Werkzeugleiste."),
            ("Tonfall & Vorlage", "Tonfall und Schreibvorlage direkt im Entwurfsfenster steuern."),
            ("Prompt-Transparenz", "KI-Systemprompt vor der Ausführung einsehen und anpassen."),
        ],
        "labels": {
            "main": "Hauptfenster",
            "compose": "Entwurfsfenster",
            "workflows": "Einstellungen → KI-Workflows",
            "tray": "Tray-Presets",
        },
        "compose_input": "Bitte hilf mir, eine knappe Nachfass-E-Mail zu unserem heutigen Produktmeeting zu schreiben.",
        "compose_output": "Hallo zusammen,\n\nvielen Dank für die produktive Diskussion heute. Hier die vereinbarten Aufgaben:\n\n• API-Vertrag bis Freitag finalisieren\n• Review-Termin für nächsten Dienstag eintragen\n• Aktualisierte Roadmap an Stakeholder verteilen\n\nBitte meldet euch, falls ich etwas vergessen habe.\n\nViele Grüße,",
        "custom_prompt": "Formuliere eine freundliche, knappe Mitteilung. Halte alle Aufgaben direkt fest.",
        "history_entries": [
            ("Bitte verschiebe das Team-Meeting morgen auf 10 Uhr.", False),
            ("Kannst du mir danach den aktualisierten Rollout-Plan schicken?", True),
            ("Der Entwurf ist fertig und liegt im gemeinsamen Projektordner.", False),
        ],
        "tts_text": "Lies diese kurze Zusammenfassung mit den aktuellen Spracheinstellungen vor.",
        "tts_voice": "de_DE-thorsten-medium",
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


FONT_TITLE = _font(52, bold=True)
FONT_SUBTITLE = _font(21, bold=False)
FONT_FLOW = _font(17, bold=True)
FONT_FEATURE_TITLE = _font(20, bold=True)
FONT_CARD_TITLE = _font(19, bold=True)
FONT_CARD_TEXT = _font(14, bold=False)
FONT_LABEL = _font(14, bold=True)


app: QApplication | None = None


def _process_events(cycles: int = 10) -> None:
    assert app is not None
    for _ in range(cycles):
        app.processEvents()


def _grab(widget, path: Path) -> None:
    widget.show()
    _process_events()
    widget.grab().save(str(path))
    widget.hide()
    print(f"  ✓ {path.name}")


def _rounded_panel(base: Image.Image, box: tuple[int, int, int, int], radius: int = 24) -> None:
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle(box, radius=radius, fill=CARD_BG, outline=CARD_BORDER, width=2)
    glow = overlay.filter(ImageFilter.GaussianBlur(18))
    base.alpha_composite(glow)
    base.alpha_composite(overlay)


def _resize_card(image_path: Path, size: tuple[int, int]) -> Image.Image:
    if not image_path.exists():
        raise FileNotFoundError(f"Required screenshot missing for banner composite: {image_path}")
    try:
        image = Image.open(image_path).convert("RGBA")
    except OSError as exc:
        raise OSError(f"Failed to load screenshot {image_path}: {exc}") from exc
    image.thumbnail(size, Image.Resampling.LANCZOS)
    panel = Image.new("RGBA", size, (0, 0, 0, 0))
    x = (size[0] - image.width) // 2
    y = (size[1] - image.height) // 2
    panel.alpha_composite(image, (x, y))
    return panel


def _draw_multiline(draw: ImageDraw.ImageDraw, text: str, xy: tuple[int, int], width: int, font, fill: str, line_gap: int = 6) -> int:
    x, y = xy
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + line_gap
    return y


def _capture_tray_menu(config: BlitztextConfig, lang: str, path: Path) -> None:
    assert app is not None
    original_start = BlitztextApp.start_hotkey_worker
    original_load = Config.load

    def fake_start(self) -> None:  # pragma: no cover - helper only
        self.hotkey_worker = None
        self.hotkey_thread = None

    def fake_load(cls, path: Path | None = None):  # pragma: no cover - helper only
        return config

    BlitztextApp.start_hotkey_worker = fake_start
    Config.load = classmethod(fake_load)
    try:
        tray = BlitztextApp(app)
        tray.stop_hotkey_worker()
        tray.config.writing_preset = "kurz_praezise"
        tray._refresh_preset_menu()
        tray.menu.ensurePolished()
        tray.menu_preset.ensurePolished()
        tray.menu.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        tray.menu_preset.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        tray.menu.show()
        tray.menu_preset.show()
        _process_events(12)

        menu_img = tray.menu.grab().toImage()
        submenu_img = tray.menu_preset.grab().toImage()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as menu_file:
            menu_tmp = Path(menu_file.name)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as submenu_file:
            submenu_tmp = Path(submenu_file.name)
        try:
            menu_img.save(str(menu_tmp))
            submenu_img.save(str(submenu_tmp))
            menu = Image.open(menu_tmp).convert("RGBA")
            submenu = Image.open(submenu_tmp).convert("RGBA")
        finally:
            menu_tmp.unlink(missing_ok=True)
            submenu_tmp.unlink(missing_ok=True)

        canvas = Image.new("RGBA", (menu.width + submenu.width + 32, max(menu.height, submenu.height) + 12), (0, 0, 0, 0))
        canvas.alpha_composite(menu, (0, 6))
        canvas.alpha_composite(submenu, (menu.width + 32, 24))
        canvas.save(path)
        print(f"  ✓ {path.name}")

        tray.menu.close()
        tray.menu_preset.close()
        tray.tray_icon.hide()
    finally:
        BlitztextApp.start_hotkey_worker = original_start
        Config.load = original_load


def _make_banner(lang: str, out_dir: Path) -> None:
    copy = LANG_COPY[lang]
    canvas = Image.new("RGBA", CANVAS_SIZE, BACKGROUND_BOTTOM)
    bg = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(bg)
    for i in range(CANVAS_SIZE[1]):
        ratio = i / max(1, CANVAS_SIZE[1] - 1)
        top = tuple(int(int(BACKGROUND_TOP[j:j + 2], 16) * (1 - ratio) + int(BACKGROUND_BOTTOM[j:j + 2], 16) * ratio) for j in (1, 3, 5))
        bg_draw.line((0, i, CANVAS_SIZE[0], i), fill=top + (255,))
    canvas.alpha_composite(bg)

    draw = ImageDraw.Draw(canvas)
    draw.ellipse((54, 52, 126, 124), fill=(13, 150, 255, 255), outline=(70, 194, 255, 255), width=3)
    draw.ellipse((79, 74, 101, 96), fill=(8, 16, 30, 255))
    draw.rectangle((88, 94, 92, 116), fill=(8, 16, 30, 255))
    draw.arc((68, 100, 112, 132), 20, 160, fill=(70, 194, 255, 255), width=4)

    y = 44
    draw.text((150, y), "Blitztext Linux", font=FONT_TITLE, fill=TEXT_PRIMARY)
    y += FONT_TITLE.size + 10
    y = _draw_multiline(draw, copy["hero"], (150, y), 540, FONT_SUBTITLE, TEXT_SECONDARY, line_gap=4)
    y += 8
    y = _draw_multiline(draw, copy["sub"], (150, y), 540, FONT_CARD_TEXT, "#c7d8ea", line_gap=4)
    y += 12
    draw.text((150, y), copy["flow"], font=FONT_FLOW, fill=ACCENT)
    y += FONT_FLOW.size + 12
    draw.text((150, y), copy["feature_title"], font=FONT_FEATURE_TITLE, fill=TEXT_PRIMARY)

    card_positions = [
        (60, 268),
        (370, 268),
        (60, 448),
        (370, 448),
    ]
    card_w = 290
    card_h = 162
    for index, ((title, desc), (x0, y0)) in enumerate(zip(copy["chips"], card_positions, strict=False)):
        x1 = x0 + card_w
        y1 = y0 + card_h
        _rounded_panel(canvas, (x0, y0, x1, y1), radius=18)
        draw.rounded_rectangle((x0 + 16, y0 + 16, x0 + 70, y0 + 44), radius=10, fill=LABEL_BG)
        draw.text((x0 + 27, y0 + 21), copy["tag_new"] if index < 2 else "OK", font=FONT_LABEL, fill="#03111f")
        draw.text((x0 + 16, y0 + 58), title, font=FONT_CARD_TITLE, fill=TEXT_PRIMARY)
        _draw_multiline(draw, desc, (x0 + 16, y0 + 84), card_w - 30, FONT_CARD_TEXT, TEXT_SECONDARY, line_gap=4)

    screenshots = {
        "main": out_dir / f"main-idle-{lang}.png",
        "compose": out_dir / f"compose-{lang}.png",
        "workflows": out_dir / f"settings-ai-{lang}.png",
        "tray": out_dir / f"tray-menu-{lang}.png",
    }

    placements = [
        (screenshots["main"], (730, 52), (230, 230), copy["labels"]["main"]),
        (screenshots["compose"], (1000, 52), (230, 230), copy["labels"]["compose"]),
        (screenshots["workflows"], (730, 342), (230, 230), copy["labels"]["workflows"]),
        (screenshots["tray"], (1000, 342), (230, 230), copy["labels"]["tray"]),
    ]

    for image_path, (x, y), size, label in placements:
        box = (x - 12, y - 12, x + size[0] + 12, y + size[1] + 42)
        _rounded_panel(canvas, box, radius=22)
        card = _resize_card(image_path, size)
        canvas.alpha_composite(card, (x, y))
        label_w = int(draw.textlength(label, font=FONT_LABEL)) + 24
        draw.rounded_rectangle((x + 12, y + size[1] + 8, x + 12 + label_w, y + size[1] + 34), radius=10, fill=(7, 22, 39, 220))
        draw.text((x + 24, y + size[1] + 13), label, font=FONT_LABEL, fill="#dcecff")

    out_path = out_dir / copy["banner"]
    canvas.convert("RGB").save(out_path, quality=95)
    print(f"  ✓ {out_path.name}")


def _make_social_preview(screenshot_dir: Path, out_path: Path) -> None:
    canvas = Image.new("RGBA", CANVAS_SIZE, BACKGROUND_BOTTOM)
    bg = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(bg)
    for i in range(CANVAS_SIZE[1]):
        ratio = i / max(1, CANVAS_SIZE[1] - 1)
        top = tuple(int(int(BACKGROUND_TOP[j:j + 2], 16) * (1 - ratio) + int(BACKGROUND_BOTTOM[j:j + 2], 16) * ratio) for j in (1, 3, 5))
        bg_draw.line((0, i, CANVAS_SIZE[0], i), fill=top + (255,))
    canvas.alpha_composite(bg)

    draw = ImageDraw.Draw(canvas)
    x_logo, y_logo = 70, 195
    # Logo
    draw.ellipse((x_logo, y_logo, x_logo + 88, y_logo + 88), fill=(13, 150, 255, 255), outline=(70, 194, 255, 255), width=3)
    draw.ellipse((x_logo + 29, y_logo + 26, x_logo + 59, y_logo + 56), fill=(8, 16, 30, 255))
    draw.rectangle((x_logo + 41, y_logo + 50, x_logo + 47, y_logo + 79), fill=(8, 16, 30, 255))
    draw.arc((x_logo + 18, y_logo + 59, x_logo + 70, y_logo + 98), 20, 160, fill=(70, 194, 255, 255), width=4)

    # Title & Subtitle
    font_title = _font(56, bold=True)
    draw.text((x_logo + 110, y_logo + 14), "Blitztext Linux", font=font_title, fill=TEXT_PRIMARY)
    font_sub = _font(24, bold=False)
    y_sub = y_logo + 118
    draw.text((x_logo, y_sub), "Your local AI voice assistant for Linux", font=font_sub, fill=TEXT_SECONDARY)

    # Flow
    font_flow = _font(21, bold=True)
    y_flow = y_sub + 46
    draw.text((x_logo, y_flow), "Record  •  Transcribe  •  Rewrite  •  Paste", font=font_flow, fill=ACCENT)

    def _add_window_shadow(base: Image.Image, img: Image.Image, x: int, y: int, radius: int = 30, offset: tuple[int, int] = (0, 15), opacity: int = 220) -> None:
        shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(shadow)
        sx = x + offset[0]
        sy = y + offset[1]
        s_draw.rounded_rectangle((sx, sy, sx + img.width, sy + img.height), radius=20, fill=(0, 0, 0, opacity))
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius))
        base.alpha_composite(shadow)
        base.alpha_composite(img, (x, y))

    img_compose = Image.open(screenshot_dir / "compose-en.png").convert("RGBA")
    img_recording = Image.open(screenshot_dir / "main-recording-en.png").convert("RGBA")
    img_idle = Image.open(screenshot_dir / "main-idle-en.png").convert("RGBA")

    compose_scaled = img_compose.resize((550, 355), Image.Resampling.LANCZOS)
    _add_window_shadow(canvas, compose_scaled, 660, 70, radius=30, offset=(0, 14), opacity=200)

    rec_scaled = img_recording.resize((284, 252), Image.Resampling.LANCZOS)
    _add_window_shadow(canvas, rec_scaled, 580, 295, radius=34, offset=(0, 16), opacity=230)

    idle_scaled = img_idle.resize((242, 215), Image.Resampling.LANCZOS)
    _add_window_shadow(canvas, idle_scaled, 920, 335, radius=28, offset=(0, 14), opacity=210)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, quality=95)
    print(f"  ✓ {out_path.name}")


class _FakeLLMService(LLMService):
    """Minimal LLMService stub for offscreen rendering — never calls any API."""

    def __init__(self) -> None:
        self.api_key = "SCREENSHOT_DUMMY_TOKEN"
        self.writing_preset = "standard"

    def is_configured(self) -> bool:
        return True

    def rewrite_text(self, *args, **kwargs) -> str:  # type: ignore[override]
        return ""

    def build_system_prompt(self, *args, **kwargs) -> str:  # type: ignore[override]
        return ""

    def rewrite_raw(self, *args, **kwargs) -> str:  # type: ignore[override]
        return ""


class _FakePasteService(PasteService):
    """Minimal PasteService stub — suppresses all clipboard / xdotool calls."""

    def __init__(self) -> None:
        pass

    def paste(self, text: str, force_autopaste=None) -> None:
        pass


def _tab_index(tabs, key: str) -> int:
    """Resolve a settings tab by its i18n key, independent of tab order or language."""
    target = tq(key)
    for index in range(tabs.count()):
        if tabs.tabText(index) == target:
            return index
    raise ValueError(f"Settings tab not found for key {key!r} ({target!r})")


def _render_language_set(out_dir: Path, lang: str) -> None:
    assert app is not None
    copy = LANG_COPY[lang]
    set_language(lang)
    with tempfile.TemporaryDirectory(prefix=f"blitztext-assets-{lang}-") as tmp_dir:
        config = BlitztextConfig(config_dir=Path(tmp_dir))
        config.ui_language = lang
        config.writing_preset = "shorten"
        config.llm_provider = "openai"
        # Piper is the default provider and keeps the shot free of cloud errors.
        config.tts_provider = "piper"
        config.notes_folder = "/home/user/Blitztext-Notes"
        config.compose_custom_preset_text = copy.get("custom_prompt", "")

        controller = SimpleNamespace(
            gui_toggle_recording=lambda *a, **k: None,
            gui_discard=lambda *a, **k: None,
            set_dictation_mode=lambda *a, **k: None,
            show_compose_window=lambda *a, **k: None,
            show_custom_prompt=lambda *a, **k: None,
            show_history_panel=lambda *a, **k: None,
            show_settings_dialog=lambda *a, **k: None,
            show_tts_window=lambda *a, **k: None,
            main_window_preset_changed=lambda *a, **k: None,
        )

        # 1. Main Window States
        main_win = MainWindow(controller)
        main_win.set_history_count(3)
        main_win.show()

        # 1.1 Idle
        main_win.update_state("IDLE", None, None)
        _grab(main_win, out_dir / f"main-idle-{lang}.png")

        # 1.2 Recording
        main_win.update_state("RECORDING", None, None)
        main_win._timer_label.setText("00:04")
        main_win._btn_toggle._phase = 0.35
        _grab(main_win, out_dir / f"main-recording-{lang}.png")

        # 1.3 Processing
        main_win.update_state("TRANSCRIBING", None, None)
        main_win._btn_toggle._phase = 0.25
        _grab(main_win, out_dir / f"main-processing-{lang}.png")

        # 1.4 Main Menu (Popup open above the options button)
        main_win.update_state("IDLE", None, None)
        main_win._select_workflow(WorkflowType.TEXT_IMPROVER)
        main_win._options_popup.show()
        _process_events(12)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f1:
            w_tmp = Path(f1.name)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f2:
            p_tmp = Path(f2.name)
        try:
            main_win.grab().save(str(w_tmp))
            main_win._options_popup.grab().save(str(p_tmp))
            img_w = Image.open(w_tmp).convert("RGBA")
            img_p = Image.open(p_tmp).convert("RGBA")
            btn_pos = main_win._btn_options.mapTo(main_win, QPoint(main_win._btn_options.width(), 0))
            canvas_w = max(img_w.width, img_p.width + 20)
            popup_x = max(0, btn_pos.x() - img_p.width + 16)
            popup_y = 0
            w_x = (canvas_w - img_w.width) // 2
            w_y = img_p.height - 16
            canvas_h = w_y + img_w.height
            menu_comp = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            menu_comp.alpha_composite(img_p, (popup_x, popup_y))
            menu_comp.alpha_composite(img_w, (w_x, w_y))
            menu_comp_path = out_dir / f"main-menu-{lang}.png"
            menu_comp.save(str(menu_comp_path))
            print(f"  ✓ {menu_comp_path.name}")
        finally:
            w_tmp.unlink(missing_ok=True)
            p_tmp.unlink(missing_ok=True)
            main_win._options_popup.hide()

        main_win.close()

        # 2. Compose Window
        compose = ComposeWindow(_FakeLLMService(), _FakePasteService(), config)
        compose.set_input_text(copy["compose_input"])
        compose.txtOutput.setPlainText(copy["compose_output"])
        _grab(compose, out_dir / f"compose-{lang}.png")

        # 2.1 Compose with Prompt Editor expanded
        compose.edit_custom_prompt()
        compose.resize(620, 500)
        _grab(compose, out_dir / f"compose-prompt-{lang}.png")
        compose.close()

        # 3. Settings Dialog
        settings = SettingsDialog(config)
        # Per tab height so every form is fully visible without empty filler space.
        settings.tabs.setCurrentIndex(_tab_index(settings.tabs, "settings.tab.general"))
        settings.resize(560, 500)
        _grab(settings, out_dir / f"settings-general-{lang}.png")
        settings.tabs.setCurrentIndex(_tab_index(settings.tabs, "settings.tab.workflows"))
        settings.resize(560, 700)
        _grab(settings, out_dir / f"settings-ai-{lang}.png")
        settings.tabs.setCurrentIndex(_tab_index(settings.tabs, "settings.tab.speech"))
        settings.resize(560, 440)
        _grab(settings, out_dir / f"settings-speech-{lang}.png")
        settings.close()

        # 4. History Panel
        history = HistoryPanel(max_entries=50, notes_folder="")
        history.resize(420, 460)
        for text, merged in copy["history_entries"]:
            history.add_entry(text, is_dictation=merged)
        _grab(history, out_dir / f"history-{lang}.png")
        time.sleep(0.5)
        _process_events(6)
        history.close()

        # 5. TTS Window
        tts = TtsWindow(config)
        tts.resize(520, 360)
        tts.set_text(copy["tts_text"])
        # The build host has no Piper voices installed; show a representative
        # entry instead of the empty-state label.
        tts._voice_combo.blockSignals(True)
        tts._voice_combo.clear()
        tts._voice_combo.addItem(copy["tts_voice"], userData=copy["tts_voice"])
        tts._voice_combo.setEnabled(True)
        tts._voice_combo.blockSignals(False)
        _grab(tts, out_dir / f"tts-{lang}.png")
        tts.close()

        # 6. Tray Menu
        _capture_tray_menu(config, lang, out_dir / f"tray-menu-{lang}.png")

        # 7. Banner
        _make_banner(lang, out_dir)


def main() -> int:
    global app
    out_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else SCREENSHOT_DIR.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    # Wie im echten App-Start (blitztext_linux.main): zentrales App-Theme,
    # damit die Screenshots die tatsaechliche Produkt-Optik zeigen.
    theme.apply_theme(app)
    for lang in ("en", "de"):
        print(f"Generating assets for {lang} …")
        _render_language_set(out_dir, lang)
    print("Generating social preview …")
    _make_social_preview(out_dir, out_dir / "social-preview.png")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

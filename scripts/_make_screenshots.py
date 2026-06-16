"""Rendert die BlitztextLinux-GUI-Komponenten als PNG-Screenshots.

Einmaliges Hilfsskript fuer die README-Dokumentation. Instanziiert die
Fenster/Dialoge direkt und greift sie per QWidget.grab() ab — kein laufender
Tray noetig.

Aufruf:  PYTHONPATH=. .venv/bin/python scripts/_make_screenshots.py <out_dir>
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

from app.config import Config
from app.main_window import MainWindow
from app.blitztext_linux import SettingsDialog
from app.history_panel import HistoryPanel
from app.tts_window import TtsWindow


def _grab(widget, path: Path) -> None:
    widget.show()
    app = QApplication.instance()
    for _ in range(8):
        app.processEvents()
    widget.grab().save(str(path))
    widget.hide()
    print(f"  ✓ {path.name}")


def main() -> int:
    out_dir = Path(sys.argv[1]).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    config = Config.load()

    # 1) Hauptfenster
    controller = SimpleNamespace(
        gui_toggle_recording=lambda *a, **k: None,
        gui_discard=lambda *a, **k: None,
        set_dictation_mode=lambda *a, **k: None,
        show_history_panel=lambda *a, **k: None,
        show_settings_dialog=lambda *a, **k: None,
        show_tts_window=lambda *a, **k: None,
    )
    win = MainWindow(controller)
    _grab(win, out_dir / "main-window.png")

    # 2) Einstellungen — Tab 1 (Whisper & Audio, der Default-Tab)
    settings = SettingsDialog(config)
    _grab(settings, out_dir / "settings-whisper.png")
    # weitere Tabs einzeln
    for idx in range(1, settings.tabs.count()):
        settings.tabs.setCurrentIndex(idx)
        name = settings.tabs.tabText(idx).lower().replace(" ", "-").replace("&", "und")
        _grab(settings, out_dir / f"settings-{name}.png")

    # 3) Verlauf — mit Beispiel-Eintraegen
    history = HistoryPanel(max_entries=50, notes_folder="")
    history.resize(420, 460)
    history.add_entry("Treffen mit dem Team morgen um 10 Uhr verschieben.", is_dictation=False)
    history.add_entry("Bitte sende mir den aktualisierten Projektplan zu.", is_dictation=True)
    history.add_entry("Die Praesentation ist fertig und liegt im Ordner.", is_dictation=False)
    _grab(history, out_dir / "history.png")

    # 4) Vorlesen (TTS)
    tts = TtsWindow(config)
    _grab(tts, out_dir / "tts.png")

    print("Fertig.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

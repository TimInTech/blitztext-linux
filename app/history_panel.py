"""Verlauf-/Diktat-Panel fuer BlitztextLinux.

Portiert und an die monolithische Blitztext-Architektur angepasst aus
whisper-dictation app/gui/history_panel.py.

GUI-freie Logik (Notiz speichern, Diktat zusammenfuehren) liegt in
Modulfunktionen, damit sie ohne Qt/Display testbar ist.
"""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t

logger = logging.getLogger("blitztext.history")


# ---------------------------------------------------------------------------
# GUI-freie Logik (testbar ohne Qt)
# ---------------------------------------------------------------------------

def _within_home(folder: str) -> Optional[str]:
    """Loest folder auf und gibt den Pfad nur zurueck, wenn er innerhalb von
    ~ liegt (Schutz gegen Schreiben ausserhalb des Home-Verzeichnisses)."""
    if not folder:
        return None
    resolved = os.path.realpath(os.path.expanduser(folder))
    home = os.path.realpath(os.path.expanduser("~"))
    if resolved == home or resolved.startswith(home + os.sep):
        return resolved
    logger.warning("notes_folder liegt ausserhalb von ~, uebersprungen: %s", folder)
    return None


def save_dictation_note(folder: str, text: str) -> Optional[str]:
    """Speichert einen einzelnen Diktat-Eintrag als .md-Datei. Gibt den Pfad
    zurueck oder None (deaktiviert/Fehler)."""
    resolved = _within_home(folder)
    if not resolved or not text.strip():
        return None
    try:
        os.makedirs(resolved, exist_ok=True)
        now = datetime.now()
        filename = now.strftime("%Y-%m-%d_%H-%M-%S") + ".md"
        heading = now.strftime("%Y-%m-%d %H:%M:%S")
        path = os.path.join(resolved, filename)
        content = f"# {t('history.note.heading').format(heading=heading)}\n\n{text}\n"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        return path
    except FileExistsError:
        # Gleiche Sekunde -- mit Suffix erneut versuchen
        try:
            path = os.path.join(resolved, now.strftime("%Y-%m-%d_%H-%M-%S") + f"_{os.getpid()}.md")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            return path
        except OSError:
            logger.warning("Diktat-Notiz konnte nicht gespeichert werden", exc_info=True)
            return None
    except OSError:
        logger.warning("Diktat-Notiz konnte nicht gespeichert werden", exc_info=True)
        return None


def merge_dictation_text(texts: List[str]) -> str:
    """Fuegt mehrere Diktat-Texte chronologisch zusammen."""
    return "\n\n".join(t for t in texts if t and t.strip())


def save_merged_dictation(folder: str, combined: str) -> Optional[str]:
    """Speichert den zusammengefuehrten Diktat-Text als eine .md-Datei."""
    resolved = _within_home(folder)
    if not resolved or not combined.strip():
        return None
    try:
        os.makedirs(resolved, exist_ok=True)
        now = datetime.now()
        filename = t("history.note.merged_filename_prefix") + now.strftime("%Y-%m-%d_%H-%M-%S") + ".md"
        heading = now.strftime("%Y-%m-%d %H:%M:%S")
        path = os.path.join(resolved, filename)
        content = f"# {t('history.note.merged_heading').format(heading=heading)}\n\n{combined}\n"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        return path
    except OSError:
        logger.warning("Zusammengefuehrtes Diktat konnte nicht gespeichert werden", exc_info=True)
        return None


def _clipboard_write(text: str) -> None:
    """Schreibt Text ins Clipboard, passend zur laufenden Desktop-Session."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    wayland_display = os.environ.get("WAYLAND_DISPLAY")
    if runtime_dir and wayland_display and os.path.exists(os.path.join(runtime_dir, wayland_display)):
        command = ["wl-copy"]
    elif os.environ.get("DISPLAY"):
        command = ["xclip", "-selection", "clipboard"]
    else:
        return
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.communicate(input=text.encode("utf-8"), timeout=3)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        pass


# ---------------------------------------------------------------------------
# Datenmodell + Widgets
# ---------------------------------------------------------------------------

@dataclass
class HistoryEntry:
    text: str
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    source: str = "clipboard"

    @property
    def is_dictation(self) -> bool:
        return self.source == "dictation"

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @property
    def preview(self) -> str:
        if len(self.text) <= 80:
            return self.text
        return self.text[:80] + "…"


class HistoryEntryWidget(QFrame):
    """Einzelner Eintrag in der Verlaufsliste."""

    deleted = pyqtSignal(object)  # emittiert den HistoryEntry

    def __init__(self, entry: HistoryEntry, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.entry = entry
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "HistoryEntryWidget { background: palette(base); border-radius: 4px; "
            "border: 1px solid palette(mid); margin: 1px 0; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        top_row = QHBoxLayout()
        meta_text = t("history.entry.meta").format(timestamp=entry.timestamp, count=entry.word_count)
        if entry.is_dictation:
            meta_text = f"\U0001f3a4 {meta_text}"
        meta_label = QLabel(meta_text)
        meta_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        top_row.addWidget(meta_label, 1)

        self._btn_copy = QPushButton("\U0001f4cb")
        self._btn_copy.setToolTip(t("history.tooltip.copy"))
        self._btn_copy.setFixedSize(28, 24)
        self._btn_copy.clicked.connect(self._copy_to_clipboard)
        top_row.addWidget(self._btn_copy)

        btn_delete = QPushButton("✕")
        btn_delete.setToolTip(t("history.tooltip.delete"))
        btn_delete.setFixedSize(28, 24)
        btn_delete.clicked.connect(lambda: self.deleted.emit(self.entry))
        top_row.addWidget(btn_delete)

        layout.addLayout(top_row)

        preview_label = QLabel(entry.preview)
        preview_label.setWordWrap(True)
        preview_label.setStyleSheet("font-size: 12px;")
        layout.addWidget(preview_label)

    def _copy_to_clipboard(self) -> None:
        _clipboard_write(self.entry.text)
        self._btn_copy.setText("✓")
        self._btn_copy.setStyleSheet("color: #4caf50; font-weight: bold;")
        QTimer.singleShot(1500, self._reset_copy_button)

    def _reset_copy_button(self) -> None:
        self._btn_copy.setText("\U0001f4cb")
        self._btn_copy.setStyleSheet("")

    def highlight(self) -> None:
        self.setStyleSheet(
            "HistoryEntryWidget { background: #fff3cd; border-radius: 4px; "
            "border: 1px solid #ffc107; margin: 1px 0; }"
        )
        QTimer.singleShot(800, lambda: self.setStyleSheet(
            "HistoryEntryWidget { background: palette(base); border-radius: 4px; "
            "border: 1px solid palette(mid); margin: 1px 0; }"
        ))


class HistoryPanel(QWidget):
    """Scrollbares Verlaufs-/Diktat-Panel (eigenstaendiges Fenster)."""

    count_changed = pyqtSignal(int)
    merged = pyqtSignal(str)  # emittiert den Pfad der zusammengefuehrten Datei

    def __init__(
        self,
        max_entries: int = 50,
        notes_folder: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._max_entries = max(10, min(100, max_entries))
        self.notes_folder = notes_folder
        self._entries: List[HistoryEntry] = []
        self._entry_widgets: List[HistoryEntryWidget] = []
        self._clear_armed = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        header_row = QHBoxLayout()
        self._header_label = QLabel(t("history.header").format(count=0))
        self._header_label.setStyleSheet("font-size: 13px; font-weight: bold;")
        header_row.addWidget(self._header_label, 1)

        self._btn_merge = QPushButton(t("history.button.merge"))
        self._btn_merge.setToolTip(t("history.tooltip.merge"))
        self._btn_merge.clicked.connect(self._merge_dictation)
        self._btn_merge.hide()
        header_row.addWidget(self._btn_merge)

        self._btn_clear = QPushButton(t("history.button.clear_all"))
        self._btn_clear.clicked.connect(self._on_clear_clicked)
        header_row.addWidget(self._btn_clear)

        layout.addLayout(header_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setMinimumHeight(300)

        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch()

        self._scroll.setWidget(self._list_container)
        layout.addWidget(self._scroll)

    def add_entry(self, text: str, is_dictation: bool = False, source: Optional[str] = None) -> None:
        if not text or not text.strip():
            return
        if source is None:
            source = "dictation" if is_dictation else "clipboard"
        entry = HistoryEntry(text=text, source=source)
        if source == "dictation":
            save_dictation_note(self.notes_folder, entry.text)
        self._entries.insert(0, entry)

        while len(self._entries) > self._max_entries:
            removed = self._entries.pop()
            self._remove_widget_for_entry(removed)

        widget = HistoryEntryWidget(entry)
        widget.deleted.connect(self._on_entry_deleted)
        self._entry_widgets.insert(0, widget)
        self._list_layout.insertWidget(0, widget)

        widget.highlight()
        QTimer.singleShot(50, lambda: self._scroll.verticalScrollBar().setValue(0))

        self._update_header()
        self._update_merge_button()

    def _on_entry_deleted(self, entry: HistoryEntry) -> None:
        try:
            self._entries.remove(entry)
        except ValueError:
            pass
        self._remove_widget_for_entry(entry)
        self._update_header()
        self._update_merge_button()

    def _remove_widget_for_entry(self, entry: HistoryEntry) -> None:
        for widget in self._entry_widgets:
            if widget.entry is entry:
                self._entry_widgets.remove(widget)
                self._list_layout.removeWidget(widget)
                widget.deleteLater()
                break

    def _on_clear_clicked(self) -> None:
        if not self._clear_armed:
            self._clear_armed = True
            self._btn_clear.setText(t("history.button.confirm_clear"))
            self._btn_clear.setStyleSheet("color: #f44336; font-weight: bold;")
            QTimer.singleShot(3000, self._disarm_clear)
        else:
            self.clear_all()

    def _disarm_clear(self) -> None:
        self._clear_armed = False
        self._btn_clear.setText(t("history.button.clear_all"))
        self._btn_clear.setStyleSheet("")

    def clear_all(self) -> None:
        self._entries.clear()
        for widget in self._entry_widgets:
            self._list_layout.removeWidget(widget)
            widget.deleteLater()
        self._entry_widgets.clear()
        self._clear_armed = False
        self._btn_clear.setText(t("history.button.clear_all"))
        self._btn_clear.setStyleSheet("")
        self._update_header()
        self._update_merge_button()

    def _merge_dictation(self) -> None:
        dictation_texts = [e.text for e in reversed(self._entries) if e.is_dictation]
        if len(dictation_texts) < 2:
            return
        combined = merge_dictation_text(dictation_texts)
        _clipboard_write(combined)
        path = save_merged_dictation(self.notes_folder, combined)
        if path:
            self.merged.emit(path)

        self._btn_merge.setText(t("history.status.saved") if path else t("history.status.copied"))
        self._btn_merge.setStyleSheet("color: #4caf50; font-weight: bold;")
        QTimer.singleShot(2500, self._reset_merge_button)

    def _reset_merge_button(self) -> None:
        self._btn_merge.setText(t("history.button.merge"))
        self._btn_merge.setStyleSheet("")

    def _update_header(self) -> None:
        count = len(self._entries)
        self._header_label.setText(t("history.header").format(count=count))
        self.count_changed.emit(count)

    def _update_merge_button(self) -> None:
        dictation_count = sum(1 for e in self._entries if e.is_dictation)
        self._btn_merge.setVisible(dictation_count >= 2)

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @property
    def dictation_count(self) -> int:
        return sum(1 for e in self._entries if e.is_dictation)

    def set_max_entries(self, max_entries: int) -> None:
        self._max_entries = max(10, min(100, max_entries))
        while len(self._entries) > self._max_entries:
            removed = self._entries.pop()
            self._remove_widget_for_entry(removed)
        self._update_header()

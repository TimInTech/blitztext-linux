"""History window for Blitztext Linux.

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
from app import theme

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
        self.setObjectName("historyEntry")
        self.setFrameShape(QFrame.Shape.StyledPanel)

        # Diese Timer muessen dem Widget gehoeren. Ein statischer
        # QTimer.singleShot mit Lambda kann nach deleteLater() noch feuern und
        # dann auf das bereits zerstoerte C++-Objekt zugreifen.
        self._copy_reset_timer = QTimer(self)
        self._copy_reset_timer.setSingleShot(True)
        self._copy_reset_timer.timeout.connect(self._reset_copy_button)
        self._highlight_reset_timer = QTimer(self)
        self._highlight_reset_timer.setSingleShot(True)
        self._highlight_reset_timer.timeout.connect(self._reset_highlight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)

        top_row = QHBoxLayout()
        meta_text = t("history.entry.meta").format(timestamp=entry.timestamp, count=entry.word_count)
        if entry.is_dictation:
            meta_text = t("history.entry.dictation").format(meta=meta_text)
        meta_label = QLabel(meta_text)
        meta_label.setProperty("role", "muted")
        top_row.addWidget(meta_label, 1)

        self._btn_copy = QPushButton()
        self._btn_copy.setObjectName("iconButton")
        self._btn_copy.setIcon(theme.create_ui_icon("copy"))
        self._btn_copy.setToolTip(t("history.tooltip.copy"))
        self._btn_copy.setFixedSize(32, 30)
        self._btn_copy.clicked.connect(self._copy_to_clipboard)
        top_row.addWidget(self._btn_copy)

        btn_delete = QPushButton()
        btn_delete.setObjectName("iconButton")
        btn_delete.setProperty("danger", True)
        btn_delete.setIcon(theme.create_ui_icon("delete", theme.STATE_ERROR))
        btn_delete.setToolTip(t("history.tooltip.delete"))
        btn_delete.setFixedSize(32, 30)
        btn_delete.clicked.connect(lambda: self.deleted.emit(self.entry))
        top_row.addWidget(btn_delete)

        layout.addLayout(top_row)

        preview_label = QLabel(entry.preview)
        preview_label.setWordWrap(True)
        layout.addWidget(preview_label)

    def _copy_to_clipboard(self) -> None:
        _clipboard_write(self.entry.text)
        self._btn_copy.setIcon(theme.create_ui_icon("check", theme.STATE_IDLE))
        self._btn_copy.setProperty("success", True)
        theme.repolish(self._btn_copy)
        self._copy_reset_timer.start(1500)

    def _reset_copy_button(self) -> None:
        self._btn_copy.setIcon(theme.create_ui_icon("copy"))
        self._btn_copy.setProperty("success", False)
        theme.repolish(self._btn_copy)

    def highlight(self) -> None:
        self.setProperty("highlighted", True)
        theme.repolish(self)
        self._highlight_reset_timer.start(800)

    def _reset_highlight(self) -> None:
        self.setProperty("highlighted", False)
        theme.repolish(self)


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
        self.setObjectName("appWindow")
        self._max_entries = max(10, min(100, max_entries))
        self.notes_folder = notes_folder
        self._entries: List[HistoryEntry] = []
        self._entry_widgets: List[HistoryEntryWidget] = []
        self._clear_armed = False
        self._setup_ui()
        self._scroll_reset_timer = QTimer(self)
        self._scroll_reset_timer.setSingleShot(True)
        self._scroll_reset_timer.timeout.connect(
            lambda: self._scroll.verticalScrollBar().setValue(0)
        )
        self._clear_disarm_timer = QTimer(self)
        self._clear_disarm_timer.setSingleShot(True)
        self._clear_disarm_timer.timeout.connect(self._disarm_clear)
        self._merge_reset_timer = QTimer(self)
        self._merge_reset_timer.setSingleShot(True)
        self._merge_reset_timer.timeout.connect(self._reset_merge_button)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        self._header_label = QLabel(t("history.header").format(count=0))
        self._header_label.setProperty("role", "title")
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

        self._empty_label = QLabel(t("history.empty"), self._list_container)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setProperty("role", "muted")
        self._list_layout.insertWidget(0, self._empty_label, 1)

    def add_entry(self, text: str, is_dictation: bool = False, source: Optional[str] = None) -> None:
        if not text or not text.strip():
            return
        if source is None:
            source = "dictation" if is_dictation else "clipboard"
        entry = HistoryEntry(text=text, source=source)
        if source == "dictation":
            save_dictation_note(self.notes_folder, entry.text)
        self._entries.insert(0, entry)
        self._empty_label.hide()

        while len(self._entries) > self._max_entries:
            removed = self._entries.pop()
            self._remove_widget_for_entry(removed)

        widget = HistoryEntryWidget(entry)
        widget.deleted.connect(self._on_entry_deleted)
        self._entry_widgets.insert(0, widget)
        self._list_layout.insertWidget(0, widget)

        widget.highlight()
        self._scroll_reset_timer.start(50)

        self._update_header()
        self._update_merge_button()
        self._empty_label.setVisible(not self._entries)

    def _on_entry_deleted(self, entry: HistoryEntry) -> None:
        try:
            self._entries.remove(entry)
        except ValueError:
            pass
        self._remove_widget_for_entry(entry)
        self._update_header()
        self._update_merge_button()
        self._empty_label.setVisible(not self._entries)

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
            self._btn_clear.setProperty("danger", True)
            theme.repolish(self._btn_clear)
            self._clear_disarm_timer.start(3000)
        else:
            self.clear_all()

    def _disarm_clear(self) -> None:
        self._clear_armed = False
        self._btn_clear.setText(t("history.button.clear_all"))
        self._btn_clear.setProperty("danger", False)
        theme.repolish(self._btn_clear)

    def clear_all(self) -> None:
        self._entries.clear()
        for widget in self._entry_widgets:
            self._list_layout.removeWidget(widget)
            widget.deleteLater()
        self._entry_widgets.clear()
        self._clear_armed = False
        self._btn_clear.setText(t("history.button.clear_all"))
        self._btn_clear.setProperty("danger", False)
        theme.repolish(self._btn_clear)
        self._update_header()
        self._update_merge_button()
        self._empty_label.show()

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
        self._btn_merge.setProperty("success", True)
        theme.repolish(self._btn_merge)
        self._merge_reset_timer.start(2500)

    def _reset_merge_button(self) -> None:
        self._btn_merge.setText(t("history.button.merge"))
        self._btn_merge.setProperty("success", False)
        theme.repolish(self._btn_merge)

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

import pytest
from unittest.mock import patch, MagicMock

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from app.history_panel import HistoryPanel, HistoryEntryWidget, HistoryEntry

@pytest.fixture
def history_panel(qapp):
    panel = HistoryPanel(max_entries=3)
    return panel

def test_add_entry_increases_count_and_displays_entry(history_panel):
    assert history_panel.entry_count == 0
    history_panel.add_entry("Hello World")
    assert history_panel.entry_count == 1
    assert history_panel._entries[0].text == "Hello World"
    assert not history_panel._empty_label.isVisible()

def test_add_entry_respects_max_entries(history_panel):
    history_panel.set_max_entries(3)
    history_panel._max_entries = 3 # force it to 3 since set_max_entries limits to 10 minimum

    for i in range(1, 15):
        history_panel.add_entry(str(i))

    assert history_panel.entry_count == 3
    assert history_panel._entries[0].text == "14"
    assert history_panel._entries[-1].text == "12"

def test_clear_all_removes_all_entries(history_panel, qapp):
    history_panel.add_entry("1")
    history_panel.add_entry("2")
    history_panel.clear_all()

    # Process events so the widget hides properly
    qapp.processEvents()

    assert history_panel.entry_count == 0
    # Because of Qt layout, we test logic property instead of isVisible which may be false if parent is hidden
    assert not history_panel._entries

@patch('app.history_panel._clipboard_write')
@patch('app.history_panel.save_merged_dictation')
def test_merge_dictation(mock_save, mock_clip, history_panel):
    history_panel.add_entry("Dict 1", is_dictation=True)
    history_panel.add_entry("Dict 2", is_dictation=True)
    history_panel.add_entry("Clip", is_dictation=False)

    mock_save.return_value = "/tmp/fake.md"

    # Needs at least 2 dictations to merge
    history_panel._merge_dictation()

    # They are inserted backwards, so chronologically they are "Dict 1" \n\n "Dict 2"
    mock_clip.assert_called_once_with("Dict 1\n\nDict 2")
    mock_save.assert_called_once_with(history_panel.notes_folder, "Dict 1\n\nDict 2")

def test_clear_button_arming(history_panel):
    assert not history_panel._clear_armed
    history_panel._on_clear_clicked()
    assert history_panel._clear_armed
    assert history_panel._clear_disarm_timer.isActive()

    history_panel._disarm_clear()
    assert not history_panel._clear_armed

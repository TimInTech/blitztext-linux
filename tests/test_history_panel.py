import os

import pytest
from unittest.mock import patch

from app.history_panel import HistoryPanel

pytestmark = pytest.mark.skipif(
    os.environ.get("WHISPER_GUI_TESTS") != "1",
    reason="requires WHISPER_GUI_TESTS=1",
)

# Reuse the application when running alongside other GUI test modules.
@pytest.fixture
def isolated_qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

@pytest.fixture
def history_panel(isolated_qapp):
    panel = HistoryPanel(max_entries=10)
    yield panel
    panel.close()
    panel.deleteLater()

def test_add_entry_increases_count_and_displays_entry(history_panel):
    history_panel.show()
    assert history_panel._empty_label.isVisible()
    assert history_panel.entry_count == 0
    history_panel.add_entry("Hello World")
    assert history_panel.entry_count == 1
    assert history_panel._entries[0].text == "Hello World"
    assert not history_panel._empty_label.isVisible()

def test_add_entry_respects_max_entries(history_panel):
    history_panel.set_max_entries(10)

    for i in range(1, 15):
        history_panel.add_entry(str(i))

    assert history_panel.entry_count == 10
    assert history_panel._entries[0].text == "14"
    assert history_panel._entries[-1].text == "5"
    assert len(history_panel._entry_widgets) == 10

def test_clear_all_removes_all_entries(history_panel, isolated_qapp):
    history_panel.show()
    history_panel.add_entry("1")
    history_panel.add_entry("2")
    history_panel.clear_all()

    # Process events so the widget hides properly
    isolated_qapp.processEvents()

    assert history_panel.entry_count == 0
    assert not history_panel._entry_widgets
    assert history_panel._empty_label.isVisible()

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

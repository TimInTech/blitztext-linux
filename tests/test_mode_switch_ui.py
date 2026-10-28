"""Main window: the visible Local | With AI switch and the popup that follows it."""
from __future__ import annotations

import os

import pytest

_GUI = os.environ.get("WHISPER_GUI_TESTS") == "1"
gui_only = pytest.mark.skipif(not _GUI, reason="benötigt WHISPER_GUI_TESTS=1 (Display)")


@pytest.fixture(autouse=True)
def _german_ui():
    from app.i18n import get_language, set_language

    previous = get_language()
    set_language("de")
    yield
    set_language(previous)


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _Controller:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, *args))
        return call


def _window(qapp, controller=None):
    from app.main_window import MainWindow

    window = MainWindow(controller or _Controller())
    window.show()
    qapp.processEvents()
    return window


@gui_only
def test_switch_is_visible_and_starts_on_local(qapp):
    from app.workflows import WorkflowType

    window = _window(qapp)
    assert window._seg_local.isVisible() and window._seg_ai.isVisible()
    assert window._seg_local.isChecked() and not window._seg_ai.isChecked()
    assert window._selected_workflow() == WorkflowType.LOCAL
    assert window._seg_local.text() == "Lokal" and window._seg_ai.text() == "Mit KI"


@gui_only
def test_clicking_the_switch_selects_the_workflow(qapp):
    from app.workflows import WorkflowType

    controller = _Controller()
    window = _window(qapp, controller)
    window._seg_ai.click()
    assert window._selected_workflow() == WorkflowType.TEXT_IMPROVER
    assert window._seg_ai.isChecked() and not window._seg_local.isChecked()
    window._btn_toggle.click()
    assert ("gui_toggle_recording", WorkflowType.TEXT_IMPROVER) in controller.calls
    window._seg_local.click()
    assert window._selected_workflow() == WorkflowType.LOCAL
    assert window._seg_local.isChecked()


@gui_only
def test_switch_follows_the_workflow_set_by_a_hotkey(qapp):
    from app.workflows import WorkflowType

    window = _window(qapp)
    window.update_state("RECORDING", WorkflowType.EMOJI_TEXT, None)
    assert window._seg_ai.isChecked()
    window.update_state("IDLE", WorkflowType.LOCAL, None)
    assert window._seg_local.isChecked()
    window.update_state("IDLE", WorkflowType.DAMPF_ABLASSEN, None)
    assert window._seg_ai.isChecked()


@gui_only
def test_ai_selection_survives_a_local_hotkey_recording(qapp):
    from app.workflows import WorkflowType

    window = _window(qapp)
    window._seg_ai.click()
    selected = window._selected_workflow()
    for _ in range(2):
        window.update_state("RECORDING", WorkflowType.LOCAL, None)
        window.update_state("TRANSCRIBING", WorkflowType.LOCAL, None)
        window.update_state("IDLE", None, None)
        assert window._seg_ai.isChecked()
        assert window._selected_workflow() == selected


@gui_only
def test_switch_is_locked_while_busy(qapp):
    window = _window(qapp)
    window.update_state("RECORDING", None, None)
    assert not window._seg_local.isEnabled() and not window._seg_ai.isEnabled()
    window.update_state("IDLE", None, None)
    assert window._seg_local.isEnabled() and window._seg_ai.isEnabled()


@gui_only
def test_state_line_names_local_or_ai_and_opens_the_popup(qapp):
    window = _window(qapp)
    window.set_model("base")
    window.set_llm_provider("openai")
    assert window._mode_label.text() == "Lokal · Whisper base"
    window._seg_ai.click()
    assert window._mode_label.text() == "Mit KI · OpenAI · Verbessern"
    assert "base" not in window._mode_label.text()
    window._mode_label.click()
    assert window._options_popup.isVisible()
    window._options_popup.hide()


@gui_only
def test_popup_shows_only_fields_that_apply(qapp):
    from app.workflows import WorkflowType

    window = _window(qapp)
    window._show_options_popup()
    qapp.processEvents()

    def shown():
        return {name for name, w in {
            "action": window._action_combo, "preset": window._preset_combo,
            "provider": window._provider_combo, "model": window._model_combo,
            "prompt": window._btn_prompt,
        }.items() if w.isVisible()}

    assert shown() == {"model"}
    window._seg_ai.click()
    assert shown() == {"action", "preset", "provider", "model", "prompt"}
    window.update_state("IDLE", WorkflowType.EMOJI_TEXT, None)
    assert shown() == {"action", "provider", "model"}
    window._seg_local.click()
    assert shown() == {"model"}
    window._options_popup.hide()


@gui_only
def test_popup_has_a_title_and_a_done_button_that_closes_it(qapp):
    window = _window(qapp)
    window._show_options_popup()
    assert window._popup_title.text() == "Lokal"
    window._seg_ai.click()
    assert window._popup_title.text() == "Mit KI"
    assert window._btn_done.text() == "Fertig"
    window._btn_done.click()
    assert not window._options_popup.isVisible()


@gui_only
def test_action_combo_lists_only_ai_actions_and_sets_the_workflow(qapp):
    from app.llm_service import LLM_WORKFLOWS

    window = _window(qapp)
    window._seg_ai.click()
    items = [window._action_combo.itemData(i) for i in range(window._action_combo.count())]
    assert set(items) == set(LLM_WORKFLOWS)
    target = next(w for w in items if w != window._selected_workflow())
    window._action_combo.setCurrentIndex(window._action_combo.findData(target))
    assert window._selected_workflow() == target


@gui_only
def test_clicking_the_side_that_is_already_active_keeps_the_workflow(qapp):
    from app.workflows import WorkflowType

    window = _window(qapp)
    window.update_state("IDLE", WorkflowType.LOCAL, None)
    window._seg_local.click()
    assert window._selected_workflow() == WorkflowType.LOCAL
    window.update_state("IDLE", WorkflowType.EMOJI_TEXT, None)
    window._seg_ai.click()
    assert window._selected_workflow() == WorkflowType.EMOJI_TEXT


@gui_only
def test_open_popup_keeps_its_bottom_edge_when_it_grows(qapp):
    window = _window(qapp)
    window.move(300, 380)  # low enough that the screen edge does not clamp the popup
    qapp.processEvents()
    window._show_options_popup()
    qapp.processEvents()
    bottom_before = window._options_popup.geometry().bottom()
    window._seg_ai.click()
    qapp.processEvents()
    assert window._options_popup.geometry().bottom() == bottom_before
    window._options_popup.hide()


@gui_only
def test_local_tooltip_is_honest_about_hotkeys(qapp):
    window = _window(qapp)
    assert "Hotkey" in window._seg_local.toolTip()


@gui_only
def test_local_click_after_cloud_hotkey_selects_dedicated_local_workflow(qapp):
    from app.workflows import WorkflowType

    window = _window(qapp)
    window.update_state("IDLE", WorkflowType.TRANSCRIPTION, None)
    window._seg_local.click()
    assert window._selected_workflow() == WorkflowType.LOCAL


@gui_only
def test_missing_workflow_selection_falls_back_to_local(qapp):
    from app.workflows import WorkflowType

    window = _window(qapp)
    window._workflow_combo.setCurrentIndex(-1)
    assert window._selected_workflow() == WorkflowType.LOCAL

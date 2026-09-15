"""Behavioral checks for the compact neumorphic main widget."""
from __future__ import annotations

import os

import pytest


_GUI = os.environ.get("WHISPER_GUI_TESTS") == "1"
gui_only = pytest.mark.skipif(not _GUI, reason="benötigt WHISPER_GUI_TESTS=1")


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


class _Controller:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def gui_toggle_recording(self, workflow) -> None:
        self.calls.append(("toggle", workflow))

    def gui_discard(self) -> None:
        self.calls.append("discard")

    def set_dictation_mode(self, enabled: bool) -> None:
        self.calls.append(("dictation", enabled))

    def show_compose_window(self) -> None:
        self.calls.append("compose")

    def show_custom_prompt(self) -> None:
        self.calls.append("prompt")

    def main_window_preset_changed(self, key: str) -> None:
        self.calls.append(("preset", key))

    def show_history_panel(self) -> None:
        self.calls.append("history")

    def show_tts_window(self) -> None:
        self.calls.append("tts")

    def show_settings_dialog(self) -> None:
        self.calls.append("settings")


@gui_only
def test_main_widget_keeps_only_core_controls_permanently_visible(qapp):
    from app.main_window import MainWindow

    window = MainWindow(_Controller())
    window.show()
    qapp.processEvents()

    assert window._main_panel.isVisible()
    assert not hasattr(window, "_toolbar")
    for control in (window._title_label, window._btn_minimize, window._btn_close,
                    window._btn_toggle, window._status_label, window._timer_label,
                    window._btn_edit_text, window._btn_history, window._btn_tts,
                    window._btn_settings, window._btn_options):
        assert control.isVisible()
    assert window._options_popup.isVisible() is False
    assert window._workflow_combo.isVisible() is False
    assert window._btn_discard.isVisible() is False
    assert window._btn_dictation.isVisible() is False
    assert not hasattr(window, "_presentation_header")


@gui_only
def test_host_window_is_frameless_and_panel_owns_title_and_window_controls(qapp):
    from PyQt6.QtCore import Qt
    from app.i18n import t
    from app.main_window import MainWindow

    window = MainWindow(_Controller())
    window.show()
    qapp.processEvents()

    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert "QWidget#mainWidgetWindow { background: transparent; }" in window.styleSheet()
    assert window._title_label.text() == t("app.name")
    assert window._btn_minimize.toolTip() == t("mainwindow.tooltip.minimize")
    assert window._btn_close.toolTip() == t("mainwindow.tooltip.close")
    for control in (window._title_label, window._btn_minimize, window._btn_close):
        assert control.parentWidget() is window._main_panel

    window.setWindowTitle("Blitztext Test")
    assert window._title_label.text() == "Blitztext Test"


@gui_only
def test_panel_close_button_hides_to_tray_without_quitting(qapp):
    from app.main_window import MainWindow

    controller = _Controller()
    window = MainWindow(controller)
    window.show()
    window._btn_options.click()
    qapp.processEvents()

    window._btn_close.click()
    qapp.processEvents()

    assert not window.isVisible()
    assert not window._options_popup.isVisible()
    assert controller.calls == []
    window.show()
    qapp.processEvents()
    assert window.isVisible()


@gui_only
def test_panel_minimize_button_minimizes_the_real_window(qapp, monkeypatch):
    from app.main_window import MainWindow

    minimized: list[bool] = []
    monkeypatch.setattr(MainWindow, "showMinimized", lambda self: minimized.append(True))
    window = MainWindow(_Controller())
    window.show()
    qapp.processEvents()

    window._btn_minimize.click()

    assert minimized == [True]
    assert window.isVisible()


@gui_only
def test_non_interactive_panel_areas_start_native_system_move(qapp):
    from PyQt6.QtCore import QPoint, Qt
    from PyQt6.QtTest import QTest
    from app.main_window import MainWindow

    controller = _Controller()
    window = MainWindow(controller)
    window.show()
    qapp.processEvents()
    moves: list[bool] = []

    class _Handle:
        def startSystemMove(self) -> bool:  # noqa: N802
            moves.append(True)
            return True

    window.windowHandle = lambda: _Handle()
    button = window._btn_toggle
    center = QPoint(button.width() // 2, button.height() // 2)

    QTest.mousePress(window._title_label, Qt.MouseButton.LeftButton)
    QTest.mousePress(window._status_label, Qt.MouseButton.LeftButton)
    QTest.mousePress(button, Qt.MouseButton.LeftButton, pos=QPoint(3, center.y()))
    assert len(moves) == 3
    assert button._pressed is False

    QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=center)
    QTest.mouseClick(window._btn_settings, Qt.MouseButton.LeftButton)
    assert len(moves) == 3
    assert [call for call in controller.calls if call != "settings"][0][0] == "toggle"
    assert "settings" in controller.calls


@gui_only
def test_options_are_shown_only_in_transient_popup(qapp):
    from app.main_window import MainWindow

    window = MainWindow(_Controller())
    window.show()
    qapp.processEvents()

    window._btn_options.click()
    qapp.processEvents()
    assert window._workflow_combo.isVisible()
    assert window._btn_dictation.isVisible()
    assert window._btn_discard.isVisible()

    window._options_popup.hide()
    assert window._options_popup.isVisible() is False


@gui_only
def test_single_panel_owns_microphone_status_and_tools(qapp):
    from app.main_window import MainWindow

    window = MainWindow(_Controller())
    window.show()
    qapp.processEvents()

    for control in (window._btn_toggle, window._status_label, window._btn_edit_text,
                    window._btn_history, window._btn_tts, window._btn_settings,
                    window._btn_options):
        assert control.parentWidget() is window._main_panel


@gui_only
def test_popup_preserves_all_existing_workflows(qapp):
    from app.main_window import MainWindow
    from app.workflows import WorkflowType

    window = MainWindow(_Controller())

    assert [
        window._workflow_combo.itemData(index)
        for index in range(window._workflow_combo.count())
    ] == [
        WorkflowType.TRANSCRIPTION,
        WorkflowType.LOCAL,
        WorkflowType.TEXT_IMPROVER,
        WorkflowType.DAMPF_ABLASSEN,
        WorkflowType.EMOJI_TEXT,
    ]


@gui_only
def test_toolbar_actions_keep_existing_controller_contract(qapp):
    from app.main_window import MainWindow

    controller = _Controller()
    window = MainWindow(controller)
    window.show()
    qapp.processEvents()

    window._btn_edit_text.click()
    window._btn_history.click()
    window._btn_tts.click()
    window._btn_settings.click()

    assert controller.calls == ["compose", "history", "tts", "settings"]


@gui_only
def test_dictation_popup_reflects_active_state(qapp):
    from app.i18n import t
    from app.main_window import MainWindow

    window = MainWindow(_Controller())
    window.show()
    qapp.processEvents()

    window.set_dictation_checked(True)

    assert window._btn_dictation.isChecked()
    assert window._btn_dictation.text() == t("mainwindow.button.dictation_active")


@gui_only
def test_recording_state_enables_discard_and_updates_gold_widget(qapp):
    from app.main_window import MainWindow
    from app.workflows import WorkflowType

    window = MainWindow(_Controller())
    window.show()
    qapp.processEvents()

    window.update_state("RECORDING", WorkflowType.TRANSCRIPTION, None)
    assert window._btn_toggle.mode == "RECORDING"
    assert window._btn_toggle._anim.isActive()
    assert window._btn_toggle.text() == "Stopp"
    assert window._btn_discard.isEnabled()

    window.update_state("TRANSCRIBING", WorkflowType.TRANSCRIPTION, None)
    assert window._btn_toggle.mode == "PROCESSING"
    assert window._btn_toggle._anim.isActive()
    assert window._btn_discard.isEnabled() is False
    assert window._timer_label.isVisible() is False

    window.update_state("IDLE", WorkflowType.TRANSCRIPTION, None)
    assert window._btn_toggle.mode == "IDLE"
    assert not window._btn_toggle._anim.isActive()


@pytest.fixture
def paint_errors(monkeypatch):
    """Collect exceptions raised inside Qt virtual overrides such as paintEvent.

    Without a custom sys.excepthook PyQt6 calls qFatal() and aborts the whole
    process (SIGABRT), which is exactly the production crash this guards.
    """
    import sys

    # Store text only: keeping the exception would keep its traceback frame and
    # therefore an unfinished QPainter alive beyond its paint device.
    errors: list[str] = []
    monkeypatch.setattr(
        sys, "excepthook",
        lambda exc_type, value, _tb: errors.append(f"{exc_type.__name__}: {value}"),
    )
    return errors


@gui_only
@pytest.mark.parametrize("state", ["IDLE", "RECORDING", "TRANSCRIBING", "LLM_REWRITING"])
def test_record_button_paints_every_state_without_exception(qapp, paint_errors, state):
    from app.main_window import MainWindow
    from app.workflows import WorkflowType

    window = MainWindow(_Controller())
    window.show()
    window.update_state(state, WorkflowType.TRANSCRIPTION, None)
    window._btn_toggle._tick()
    window._btn_toggle.grab()
    window.grab()

    assert paint_errors == []


@gui_only
def test_full_state_cycle_repaints_without_exception(qapp, paint_errors):
    from app.main_window import MainWindow
    from app.workflows import WorkflowType

    window = MainWindow(_Controller())
    window.show()
    for _cycle in range(3):
        for state in ("IDLE", "RECORDING", "TRANSCRIBING", "LLM_REWRITING", "IDLE"):
            window.update_state(state, WorkflowType.TRANSCRIPTION, None)
            window._btn_toggle._tick()
            window.grab()

    assert paint_errors == []
    assert window._btn_toggle.mode == "IDLE"
    assert not window._btn_toggle._anim.isActive()


def _gold_pixels(button, zone) -> int:
    """Count clearly gold pixels in a logical-coordinate zone of the button."""
    image = button.grab().toImage()
    ratio = image.width() / button.width()
    left, top, right, bottom = zone
    count = 0
    for y in range(int(top * ratio), int(bottom * ratio)):
        for x in range(int(left * ratio), int(right * ratio)):
            color = image.pixelColor(x, y)
            if color.red() > 150 and color.green() > 110 and color.red() - color.blue() > 60:
                count += 1
    return count


def _side_zones(button):
    """Left and right areas beside the processing ring, where waves belong."""
    from app.main_window import _RING_DIAMETER, _RING_PEN

    center_x = button.width() / 2
    clearance = _RING_DIAMETER / 2 + _RING_PEN / 2 + 1
    height = button.height()
    return ((0, 0, center_x - clearance, height),
            (center_x + clearance, 0, button.width(), height))


def _ring_zone(button):
    """Thin band above the mic face that only the processing ring paints."""
    from app.main_window import _RING_DIAMETER

    center_x = button.width() / 2
    ring_top = button.height() / 2 - _RING_DIAMETER / 2
    return (center_x - 20, ring_top - 1, center_x + 20, ring_top + 2)


@gui_only
def test_recording_waves_are_visible_beside_the_microphone(qapp, paint_errors):
    from app.main_window import MainWindow
    from app.workflows import WorkflowType

    window = MainWindow(_Controller())
    window.show()
    button = window._btn_toggle
    left, right = _side_zones(button)

    assert _gold_pixels(button, left) == 0
    assert _gold_pixels(button, right) == 0

    window.update_state("RECORDING", WorkflowType.TRANSCRIPTION, None)
    for _ in range(5):
        button._tick()
        assert _gold_pixels(button, left) > 40
        assert _gold_pixels(button, right) > 40
    assert button._anim.isActive()
    assert paint_errors == []


@gui_only
def test_recording_waves_move_over_time(qapp):
    from app.main_window import MainWindow
    from app.workflows import WorkflowType

    window = MainWindow(_Controller())
    window.show()
    button = window._btn_toggle
    window.update_state("RECORDING", WorkflowType.TRANSCRIPTION, None)

    first = button.grab().toImage()
    for _ in range(4):
        button._tick()
    assert button.grab().toImage() != first


@gui_only
def test_processing_replaces_waves_with_gold_ring_and_idle_clears_both(qapp, paint_errors):
    from app.main_window import MainWindow
    from app.workflows import WorkflowType

    window = MainWindow(_Controller())
    window.show()
    button = window._btn_toggle
    left, right = _side_zones(button)
    ring = _ring_zone(button)
    idle_ring_pixels = _gold_pixels(button, ring)

    window.update_state("RECORDING", WorkflowType.TRANSCRIPTION, None)
    button._tick()
    window.update_state("TRANSCRIBING", WorkflowType.TRANSCRIPTION, None)
    button._tick()
    assert button._anim.isActive()
    assert _gold_pixels(button, left) == 0
    assert _gold_pixels(button, right) == 0
    assert _gold_pixels(button, ring) > idle_ring_pixels + 20

    window.update_state("IDLE", WorkflowType.TRANSCRIPTION, None)
    assert not button._anim.isActive()
    assert _gold_pixels(button, left) == 0
    assert _gold_pixels(button, right) == 0
    assert _gold_pixels(button, ring) == idle_ring_pixels
    assert paint_errors == []


@gui_only
def test_only_the_round_microphone_is_clickable(qapp):
    from PyQt6.QtCore import QPoint
    from app.main_window import MainWindow

    window = MainWindow(_Controller())
    button = window._btn_toggle
    center = QPoint(button.width() // 2, button.height() // 2)

    assert button.hitButton(center)
    assert not button.hitButton(QPoint(4, center.y()))
    assert not button.hitButton(QPoint(button.width() - 4, center.y()))


def _shown_window(qapp):
    from app import theme
    from app.main_window import MainWindow

    theme.apply_theme(qapp)
    window = MainWindow(_Controller())
    window.show()
    qapp.processEvents()
    return window


@gui_only
def test_root_layout_holds_exactly_one_surface(qapp):
    from PyQt6.QtWidgets import QFrame

    window = _shown_window(qapp)
    root = window.layout()

    widgets = [root.itemAt(index).widget() for index in range(root.count())]
    assert widgets == [window._main_panel]
    frames = [child for child in window.findChildren(QFrame)
              if child.parentWidget() is window and not child.isWindow()]
    assert frames == [window._main_panel]
    # Transient options live in their own popup window, not in the layout.
    assert window._options_popup.isWindow()


@gui_only
def test_header_microphone_status_and_tools_stack_inside_the_panel(qapp):
    window = _shown_window(qapp)
    inner = window._main_panel.contentsRect()
    title = window._title_label.geometry()
    close = window._btn_close.geometry()
    record = window._btn_toggle.geometry()
    status = window._status_label.geometry()
    options = window._btn_options.geometry()

    for rect in (title, close, window._btn_minimize.geometry(), record, status,
                 window._btn_edit_text.geometry(), options):
        assert inner.contains(rect)
    assert title.bottom() <= record.top()
    assert close.bottom() <= record.top()
    assert record.bottom() <= status.top()
    assert status.bottom() < options.top()
    # Header controls and tool row share the panel's right edge.
    assert close.right() == options.right()
    assert window._btn_minimize.geometry().right() < close.left()
    assert abs(record.center().x() - inner.center().x()) <= 1


@gui_only
def test_toolbar_buttons_keep_full_size_after_stylesheet_polish(qapp):
    from app import theme

    window = _shown_window(qapp)
    buttons = (window._btn_edit_text, window._btn_history, window._btn_tts,
               window._btn_settings, window._btn_options)

    for button in buttons:
        assert button.height() == theme.TOOL_BUTTON_SIZE
        assert button.width() >= theme.TOOL_BUTTON_SIZE
    for control in (window._btn_minimize, window._btn_close):
        assert control.size().width() == theme.WINDOW_BUTTON_SIZE
        assert control.size().height() == theme.WINDOW_BUTTON_SIZE
    # Outer buttons sit symmetrically inside the panel.
    left_gap = buttons[0].geometry().left()
    right_gap = window._main_panel.width() - buttons[-1].geometry().right() - 1
    assert abs(left_gap - right_gap) <= 1


@gui_only
def test_window_size_follows_compact_content_with_small_shadow_margins(qapp):
    window = _shown_window(qapp)
    panel = window._main_panel.geometry()

    assert window.size() == window.layout().sizeHint()
    assert 200 <= panel.width() <= 250
    assert 170 <= panel.height() <= 220
    assert panel.left() <= 12
    assert window.width() - panel.right() - 1 <= 12
    assert panel.top() <= 8
    assert window.height() - panel.bottom() - 1 <= 16
    assert window.width() <= 260 and window.height() <= 236
    # The panel has no dead filler around its content.
    assert panel.size() == window._main_panel.sizeHint()


@gui_only
def test_shadows_fade_out_before_the_window_edge(qapp):
    window = _shown_window(qapp)
    image = window.grab().toImage()
    width, height = image.width(), image.height()

    edge_alpha = [image.pixelColor(x, y).alpha()
                  for x in range(width) for y in (0, height - 1)]
    edge_alpha += [image.pixelColor(x, y).alpha()
                   for y in range(height) for x in (0, width - 1)]
    assert max(edge_alpha) <= 3


@gui_only
def test_window_size_stays_stable_across_state_cycles(qapp, paint_errors):
    from app.workflows import WorkflowType

    window = _shown_window(qapp)
    size = window.size()
    panel = window._main_panel.geometry()
    for _cycle in range(3):
        for state in ("RECORDING", "TRANSCRIBING", "LLM_REWRITING", "IDLE"):
            window.update_state(state, WorkflowType.TRANSCRIPTION, None)
            window.set_history_count(999)
            qapp.processEvents()
            assert window.size() == size
            assert window._main_panel.geometry() == panel
    window.update_state("IDLE", WorkflowType.TRANSCRIPTION, "boom")
    qapp.processEvents()
    assert window.size() == size
    assert paint_errors == []


@gui_only
def test_history_count_fits_inside_its_toolbar_button(qapp):
    window = _shown_window(qapp)
    window.set_history_count(999)
    qapp.processEvents()

    button = window._btn_history
    assert button.width() >= button.sizeHint().width()


@gui_only
def test_close_hides_window_to_tray_and_it_can_be_reopened(qapp):
    window = _shown_window(qapp)
    window._btn_options.click()
    qapp.processEvents()

    assert window.close() is False
    assert not window.isVisible()
    assert not window._options_popup.isVisible()

    window.show()
    qapp.processEvents()
    assert window.isVisible()


@gui_only
def test_record_button_keeps_full_custom_paint_area_after_qss_polish(qapp):
    from app.main_window import MainWindow

    from app import theme

    window = MainWindow(_Controller())
    window.show()
    qapp.processEvents()

    from app.main_window import (_RING_DIAMETER, _RING_PEN, _WAVE_BARS,
                                 _WAVE_CLEARANCE, _WAVE_PITCH, _WAVE_WIDTH)

    assert window._btn_toggle.size().width() == theme.RECORD_BUTTON_WIDTH
    assert window._btn_toggle.size().height() == theme.RECORD_BUTTON_HEIGHT
    # The waves need room beside the round microphone, the ring above and below.
    wave_reach = _WAVE_CLEARANCE + (_WAVE_BARS - 1) * _WAVE_PITCH + _WAVE_WIDTH / 2
    assert theme.RECORD_BUTTON_WIDTH >= 2 * wave_reach
    assert theme.RECORD_BUTTON_HEIGHT >= _RING_DIAMETER + _RING_PEN


def test_brand_bolt_is_read_from_the_official_logo_asset():
    from app import theme

    capsule, points = theme._brand_bolt_geometry()

    assert theme.BRAND_MARK_SVG.is_file()
    assert capsule == (16.0, 6.0, 16.0, 26.0)
    assert points == ((26, 11), (20, 20), (24, 20), (22, 27), (28, 17.5), (24, 17.5))
    # The fallback describes exactly the same bolt.
    assert tuple(theme._svg_path_points(theme._BRAND_BOLT_FALLBACK)) == points


def test_brand_bolt_keeps_logo_proportions_inside_the_capsule():
    from PyQt6.QtCore import QRectF
    from app import theme

    capsule = QRectF(-11, -31, 22, 49)
    bolt = theme.brand_bolt_path(capsule).boundingRect()

    # Logo: bolt 8 x 16 inside a 16 px wide capsule, centered on it.
    assert bolt.width() == pytest.approx(capsule.width() / 2)
    assert bolt.height() == pytest.approx(capsule.width())
    assert bolt.center().x() == pytest.approx(capsule.center().x())
    assert bolt.center().y() == pytest.approx(capsule.center().y())
    assert capsule.contains(bolt)


@gui_only
@pytest.mark.parametrize("state", ["IDLE", "RECORDING", "TRANSCRIBING", "LLM_REWRITING"])
def test_brand_bolt_stays_cut_into_the_gold_microphone_in_every_state(
    qapp, paint_errors, state,
):
    from PyQt6.QtCore import QPointF
    from app import theme
    from app.main_window import _ART_SCALE, _MIC_CAPSULE, MainWindow
    from app.workflows import WorkflowType

    window = MainWindow(_Controller())
    window.show()
    window.update_state(state, WorkflowType.TRANSCRIPTION, None)
    button = window._btn_toggle
    button._tick()
    image = button.grab().toImage()
    ratio = image.width() / button.width()

    def pixel(point: QPointF):
        x = button.width() / 2 + point.x() * _ART_SCALE
        y = button.height() / 2 + point.y() * _ART_SCALE
        return image.pixelColor(int(x * ratio), int(y * ratio))

    bolt = theme.brand_bolt_path(_MIC_CAPSULE)
    # Middle of the bolt's widest band, between its two horizontal edges.
    inner = (QPointF(bolt.elementAt(2).x, bolt.elementAt(2).y)
             + QPointF(bolt.elementAt(5).x, bolt.elementAt(5).y)) / 2
    assert bolt.contains(inner)
    cut = pixel(inner)
    assert cut.lightness() < 90, cut.name()
    gold = pixel(QPointF(inner.x(), bolt.boundingRect().top() - 4))
    assert gold.red() > 150 and gold.green() > 110 and gold.red() - gold.blue() > 60
    assert paint_errors == []

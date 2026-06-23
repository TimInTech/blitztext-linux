"""Tests for the compose window and its direct text rewrite flow."""
from __future__ import annotations

import os
import time

import pytest

from app.compose_window import MAX_COMPOSE_VARIANTS, ComposeWindow
from app.i18n import DEFAULT_LANGUAGE, missing_keys, set_language, t
from app.workflows import WorkflowType

_GUI = os.environ.get("WHISPER_GUI_TESTS") == "1"
gui_only = pytest.mark.skipif(not _GUI, reason="benötigt WHISPER_GUI_TESTS=1 (Display)")


class _FakeLLMService:
    def __init__(self, result: str = "OK", error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[WorkflowType, str, str | None]] = []
        self.api_key = "DUMMY_COMPOSE_SECRET_TOKEN_123"
        self.writing_preset = "standard"

    def rewrite_text(
        self,
        workflow: WorkflowType,
        text: str,
        writing_preset: str | None = None,
    ) -> str:
        self.calls.append((workflow, text, writing_preset))
        if self.error is not None:
            raise self.error
        return self.result


class _FakePasteService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool | None]] = []

    def paste(self, text: str, force_autopaste: bool | None = None) -> None:
        self.calls.append((text, force_autopaste))


class _FakeClipboard:
    def __init__(self) -> None:
        self.text = ""

    def setText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self.text = text


@pytest.fixture(autouse=True)
def reset_language():
    set_language(DEFAULT_LANGUAGE)
    yield
    set_language(DEFAULT_LANGUAGE)


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def compose_window(qapp):
    llm = _FakeLLMService()
    paste = _FakePasteService()
    window = ComposeWindow(llm, paste)
    window.show()
    qapp.processEvents()
    yield window, llm, paste
    window.close()
    qapp.processEvents()


def _wait_until(qapp, predicate, timeout_ms: int = 2500) -> None:
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    qapp.processEvents()
    assert predicate(), "Timed out waiting for compose window state change"


@gui_only
@pytest.mark.parametrize(
    ("language", "title"),
    [
        ("de", "Text verfassen"),
        ("en", "Compose Text"),
    ],
)
def test_window_texts_follow_language(qapp, language, title):
    set_language(language)
    window = ComposeWindow(_FakeLLMService(), _FakePasteService())
    try:
        assert window.windowTitle() == title
        assert window.btnAction.text() == t("compose.button.improve")
        assert window.btnCopy.text() == t("compose.button.copy")
        assert window.btnPaste.text() == t("compose.button.insert_close")
        assert window.btnClose.text() == t("compose.button.close")
    finally:
        window.close()
        qapp.processEvents()


@gui_only
def test_window_opens_without_llm_call(compose_window):
    window, llm, _paste = compose_window

    assert llm.calls == []
    assert window.btnAction.isEnabled() is False
    assert window.btnCopy.isEnabled() is False
    assert window.btnPaste.isEnabled() is False
    assert window.lblStatus.isVisible() is False


@gui_only
def test_input_reaches_direct_llm_path_and_sets_output(compose_window, qapp):
    window, llm, _paste = compose_window

    window.cmbWorkflow.setCurrentIndex(window.cmbWorkflow.findData(WorkflowType.TEXT_IMPROVER))
    window.cmbPreset.setCurrentIndex(window.cmbPreset.findData("email_formal"))
    window.txtInput.setPlainText("Hallo Welt")
    window.btnAction.click()

    _wait_until(
        qapp,
        lambda: not window._busy and window._worker_thread is None and window.txtOutput.toPlainText() == "OK",
    )

    assert llm.calls == [
        (WorkflowType.TEXT_IMPROVER, "Hallo Welt", "email_formal"),
    ]
    assert window.txtOutput.toPlainText() == "OK"
    assert window.btnCopy.isEnabled() is True
    assert window.btnPaste.isEnabled() is True
    assert window.txtInput.isReadOnly() is False


@gui_only
def test_copy_writes_result_to_clipboard(compose_window, monkeypatch, qapp):
    window, _llm, _paste = compose_window
    from PyQt6.QtWidgets import QApplication

    clipboard = _FakeClipboard()
    monkeypatch.setattr(QApplication, "clipboard", lambda: clipboard)

    window.txtOutput.setPlainText("Final result")
    window.btnCopy.click()
    qapp.processEvents()

    assert clipboard.text == "Final result"


@gui_only
def test_insert_calls_paste_service_and_closes(qapp):
    llm = _FakeLLMService()
    paste = _FakePasteService()
    window = ComposeWindow(llm, paste)
    window.show()
    qapp.processEvents()

    try:
        window.txtOutput.setPlainText("Final result")
        window.btnPaste.click()
        qapp.processEvents()

        assert paste.calls == [("Final result", True)]
        assert window.isVisible() is False
    finally:
        window.close()
        qapp.processEvents()


@gui_only
def test_empty_input_disables_improve(compose_window):
    window, _llm, _paste = compose_window

    window.txtInput.setPlainText("   ")
    assert window.btnAction.isEnabled() is False

    window.txtInput.setPlainText("Ein Satz")
    assert window.btnAction.isEnabled() is True


@gui_only
def test_errors_are_visible_and_scrubbed(qapp):
    llm = _FakeLLMService(error=RuntimeError("boom DUMMY_COMPOSE_SECRET_TOKEN_123"))
    paste = _FakePasteService()
    window = ComposeWindow(llm, paste)
    window.show()
    qapp.processEvents()

    try:
        window.txtInput.setPlainText("Bitte umschreiben")
        window.btnAction.click()

        _wait_until(
            qapp,
            lambda: not window._busy and window._worker_thread is None and bool(window.lblStatus.text()),
        )

        assert window.lblStatus.isVisible() is True
        assert "DUMMY_COMPOSE_SECRET_TOKEN_123" not in window.lblStatus.text()
        assert "boom" in window.lblStatus.text()
        assert window.txtOutput.toPlainText() == ""
        assert window.btnCopy.isEnabled() is False
        assert window.btnPaste.isEnabled() is False
        assert window.btnAction.isEnabled() is True
    finally:
        window.close()
        qapp.processEvents()


@gui_only
def test_no_autopaste_after_llm_success(compose_window, qapp):
    """LLM-Erfolg setzt das Ergebnis, löst aber KEINEN automatischen Paste aus."""
    window, _llm, paste = compose_window

    window.txtInput.setPlainText("Hallo Welt")
    window.btnAction.click()

    _wait_until(
        qapp,
        lambda: not window._busy and window._worker_thread is None and window.txtOutput.toPlainText() == "OK",
    )

    assert window.txtOutput.toPlainText() == "OK"
    assert paste.calls == []
    assert window.isVisible() is True


@gui_only
def test_voice_routing_checkbox_visible_and_disabled(compose_window, qapp):
    """Voice-Routing-Checkbox ist vorhanden, sichtbar und deaktiviert (Future-Hook)."""
    window, _llm, _paste = compose_window

    chk = window.chkVoiceRouting
    assert chk is not None
    assert chk.isVisible() is True
    assert chk.isEnabled() is False
    assert chk.text() == t("compose.voice_routing.label")


# ---------------------------------------------------------------------------
# Paket I-2: Varianten-Verlauf
# ---------------------------------------------------------------------------


def _run_generation(window, llm, qapp, text: str, result: str) -> None:
    """Trigger one successful LLM generation and wait for completion."""
    before = len(llm.calls)
    llm.result = result
    window.txtInput.setPlainText(text)
    window.btnAction.click()
    _wait_until(
        qapp,
        lambda: len(llm.calls) > before
        and not window._busy
        and window._worker_thread is None,
    )
    _wait_until(qapp, lambda: window.txtOutput.toPlainText() == result)


def _counter(current: int, total: int) -> str:
    return t("compose.variant.counter").format(current=current, total=total)


@gui_only
def test_first_generation_creates_single_variant(compose_window, qapp):
    window, llm, _paste = compose_window

    _run_generation(window, llm, qapp, "Eingabe", "Erstes Ergebnis")

    assert window._variants == ["Erstes Ergebnis"]
    assert window._variant_index == 0
    assert window.txtOutput.toPlainText() == "Erstes Ergebnis"
    assert window.lblVariantCounter.isVisible() is True
    assert window.lblVariantCounter.text() == _counter(1, 1)
    assert window.btnPrev.isEnabled() is False
    assert window.btnNext.isEnabled() is False


@gui_only
def test_second_generation_appends_and_moves_index_to_end(compose_window, qapp):
    window, llm, _paste = compose_window

    _run_generation(window, llm, qapp, "A", "Var 1")
    _run_generation(window, llm, qapp, "B", "Var 2")

    assert window._variants == ["Var 1", "Var 2"]
    assert window._variant_index == 1
    assert window.txtOutput.toPlainText() == "Var 2"
    assert window.lblVariantCounter.text() == _counter(2, 2)


@gui_only
def test_navigation_updates_output_counter_and_button_state(compose_window, qapp):
    window, llm, _paste = compose_window

    _run_generation(window, llm, qapp, "A", "Var 1")
    _run_generation(window, llm, qapp, "B", "Var 2")

    # At the end: next disabled, prev enabled.
    assert window.btnNext.isEnabled() is False
    assert window.btnPrev.isEnabled() is True

    window.btnPrev.click()
    qapp.processEvents()
    assert window._variant_index == 0
    assert window.txtOutput.toPlainText() == "Var 1"
    assert window.lblVariantCounter.text() == _counter(1, 2)
    assert window.btnPrev.isEnabled() is False
    assert window.btnNext.isEnabled() is True

    window.btnNext.click()
    qapp.processEvents()
    assert window._variant_index == 1
    assert window.txtOutput.toPlainText() == "Var 2"
    assert window.lblVariantCounter.text() == _counter(2, 2)
    assert window.btnNext.isEnabled() is False


@gui_only
def test_ring_buffer_trims_oldest_variant(compose_window, qapp):
    window, llm, _paste = compose_window

    for i in range(MAX_COMPOSE_VARIANTS + 1):
        _run_generation(window, llm, qapp, f"In {i}", f"V{i}")

    assert len(window._variants) == MAX_COMPOSE_VARIANTS
    # Oldest ("V0") trimmed, newest at the end.
    assert window._variants[0] == "V1"
    assert window._variants[-1] == f"V{MAX_COMPOSE_VARIANTS}"
    assert window._variant_index == MAX_COMPOSE_VARIANTS - 1
    assert window.lblVariantCounter.text() == _counter(
        MAX_COMPOSE_VARIANTS, MAX_COMPOSE_VARIANTS
    )


@gui_only
def test_copy_and_paste_use_displayed_variant_after_navigation(qapp, monkeypatch):
    from PyQt6.QtWidgets import QApplication

    llm = _FakeLLMService()
    paste = _FakePasteService()
    window = ComposeWindow(llm, paste)
    window.show()
    qapp.processEvents()
    clipboard = _FakeClipboard()
    monkeypatch.setattr(QApplication, "clipboard", lambda: clipboard)

    try:
        _run_generation(window, llm, qapp, "A", "Var 1")
        _run_generation(window, llm, qapp, "B", "Var 2")

        window.btnPrev.click()
        qapp.processEvents()
        assert window.txtOutput.toPlainText() == "Var 1"

        window.btnCopy.click()
        qapp.processEvents()
        assert clipboard.text == "Var 1"

        window.btnPaste.click()
        qapp.processEvents()
        assert paste.calls[-1] == ("Var 1", True)
    finally:
        window.close()
        qapp.processEvents()


@gui_only
def test_set_input_text_clears_variant_history(compose_window, qapp):
    window, llm, _paste = compose_window

    _run_generation(window, llm, qapp, "A", "Var 1")
    _run_generation(window, llm, qapp, "B", "Var 2")
    assert len(window._variants) == 2

    window.set_input_text("Neuer Kontext")

    assert window._variants == []
    assert window._variant_index == -1
    assert window.txtOutput.toPlainText() == ""
    assert window.lblVariantCounter.isVisible() is False
    assert window.btnPrev.isVisible() is False
    assert window.btnNext.isVisible() is False


@gui_only
def test_error_run_creates_no_variant(qapp):
    llm = _FakeLLMService(error=RuntimeError("boom"))
    paste = _FakePasteService()
    window = ComposeWindow(llm, paste)
    window.show()
    qapp.processEvents()

    try:
        window.txtInput.setPlainText("Bitte umschreiben")
        window.btnAction.click()
        _wait_until(
            qapp,
            lambda: not window._busy
            and window._worker_thread is None
            and bool(window.lblStatus.text()),
        )

        assert window._variants == []
        assert window._variant_index == -1
        assert window.lblVariantCounter.isVisible() is False
    finally:
        window.close()
        qapp.processEvents()


@gui_only
def test_manual_edit_persists_in_place_across_navigation(compose_window, qapp):
    window, llm, _paste = compose_window

    _run_generation(window, llm, qapp, "A", "Var 1")
    _run_generation(window, llm, qapp, "B", "Var 2")

    # Manual edit of the currently displayed (second) variant.
    window.txtOutput.setPlainText("Var 2 editiert")
    qapp.processEvents()
    assert window._variants[1] == "Var 2 editiert"

    window.btnPrev.click()
    qapp.processEvents()
    assert window.txtOutput.toPlainText() == "Var 1"

    window.btnNext.click()
    qapp.processEvents()
    assert window.txtOutput.toPlainText() == "Var 2 editiert"
    assert window._variants[0] == "Var 1"


@gui_only
def test_navigation_disabled_while_busy(qapp):
    import threading

    release = threading.Event()

    class _BlockingLLM(_FakeLLMService):
        def rewrite_text(self, workflow, text, writing_preset=None):
            self.calls.append((workflow, text, writing_preset))
            release.wait(2.0)
            return self.result

    llm = _BlockingLLM(result="Var 2")
    paste = _FakePasteService()
    window = ComposeWindow(llm, paste)
    window.show()
    qapp.processEvents()

    try:
        _run_generation(window, llm, qapp, "A", "Var 1")
        assert window.btnPrev.isEnabled() is False  # single variant border

        # Start a second, blocking generation.
        release.clear()
        window.txtInput.setPlainText("B")
        window.btnAction.click()
        _wait_until(qapp, lambda: window._busy)

        assert window._busy is True
        assert window.btnPrev.isEnabled() is False
        assert window.btnNext.isEnabled() is False

        release.set()
        _wait_until(
            qapp,
            lambda: not window._busy and window._worker_thread is None,
        )
    finally:
        release.set()
        window.close()
        qapp.processEvents()


@gui_only
@pytest.mark.parametrize("language", ["de", "en"])
def test_variant_i18n_keys_present_and_complete(qapp, language):
    set_language(language)
    window = ComposeWindow(_FakeLLMService(), _FakePasteService())
    try:
        assert missing_keys() == set()
        counter = t("compose.variant.counter").format(current=1, total=2)
        assert "1" in counter and "2" in counter
        assert t("compose.variant.prev") != "compose.variant.prev"
        assert t("compose.variant.next") != "compose.variant.next"
    finally:
        window.close()
        qapp.processEvents()

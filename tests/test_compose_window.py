"""Tests for the compose window and its direct text rewrite flow."""
from __future__ import annotations

import os
import time

import pytest

from app.compose_window import ComposeWindow
from app.i18n import DEFAULT_LANGUAGE, set_language, t
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

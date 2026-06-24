"""Tests for the compose window and its direct text rewrite flow."""
from __future__ import annotations

import os
import time

import pytest

from app.compose_window import MAX_COMPOSE_VARIANTS, ComposeWindow
from app.config import Config
from app.i18n import DEFAULT_LANGUAGE, missing_keys, set_language, t
from app.workflows import WorkflowType

_GUI = os.environ.get("WHISPER_GUI_TESTS") == "1"
gui_only = pytest.mark.skipif(not _GUI, reason="benötigt WHISPER_GUI_TESTS=1 (Display)")


class _FakeLLMService:
    def __init__(self, result: str = "OK", error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[WorkflowType, str, str | None]] = []
        # Separate records keep the legacy 3-tuple ``calls`` assertions intact
        # while still exposing the new tone/custom_prompt plumbing.
        self.tone_calls: list[str | None] = []
        self.custom_prompt_calls: list[str | None] = []
        self.api_key = "DUMMY_COMPOSE_SECRET_TOKEN_123"
        self.writing_preset = "standard"

    def rewrite_text(
        self,
        workflow: WorkflowType,
        text: str,
        writing_preset: str | None = None,
        tone: str | None = None,
        custom_prompt: str | None = None,
    ) -> str:
        self.calls.append((workflow, text, writing_preset))
        self.tone_calls.append(tone)
        self.custom_prompt_calls.append(custom_prompt)
        if self.error is not None:
            raise self.error
        return self.result

    def build_system_prompt(
        self,
        workflow: WorkflowType,
        writing_preset: str | None = None,
        tone: str | None = None,
        custom_prompt: str | None = None,
    ) -> str:
        return f"[FAKE_SYSTEM:{workflow.value}]"

    def rewrite_raw(self, system_prompt: str, user_message: str) -> str:
        self.calls.append((WorkflowType.TEXT_IMPROVER, user_message, None))
        self.tone_calls.append(None)
        self.custom_prompt_calls.append(system_prompt)
        if self.error is not None:
            raise self.error
        return self.result

    @property
    def last_tone(self) -> str | None:
        return self.tone_calls[-1] if self.tone_calls else None

    @property
    def last_custom_prompt(self) -> str | None:
        return self.custom_prompt_calls[-1] if self.custom_prompt_calls else None


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


@pytest.fixture(autouse=True)
def _isolated_config_home(tmp_path, monkeypatch):
    """Keep the developer's real ~/.config/blitztext-linux out of these tests.

    ``ComposeWindow`` reads the live ``Config`` (signature, auto-append, custom
    preset text). Pointing ``HOME`` at a temp dir guarantees clean defaults, so
    assertions like ``output == "OK"`` stay deterministic regardless of locally
    saved settings. CI already runs against a clean home; this makes local runs
    match it.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    yield


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def compose_window(qapp):
    llm = _FakeLLMService()
    paste = _FakePasteService()
    window = ComposeWindow(llm, paste, Config())
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
    window = ComposeWindow(_FakeLLMService(), _FakePasteService(), Config())
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
    window = ComposeWindow(llm, paste, Config())
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
    window = ComposeWindow(llm, paste, Config())
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
    window = ComposeWindow(llm, paste, Config())
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
    window = ComposeWindow(llm, paste, Config())
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
        def rewrite_text(self, workflow, text, writing_preset=None, tone=None, custom_prompt=None):
            self.calls.append((workflow, text, writing_preset))
            self.tone_calls.append(tone)
            self.custom_prompt_calls.append(custom_prompt)
            release.wait(2.0)
            return self.result

    llm = _BlockingLLM(result="Var 2")
    paste = _FakePasteService()
    window = ComposeWindow(llm, paste, Config())
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
    window = ComposeWindow(_FakeLLMService(), _FakePasteService(), Config())
    try:
        assert missing_keys() == set()
        counter = t("compose.variant.counter").format(current=1, total=2)
        assert "1" in counter and "2" in counter
        assert t("compose.variant.prev") != "compose.variant.prev"
        assert t("compose.variant.next") != "compose.variant.next"
    finally:
        window.close()
        qapp.processEvents()


@gui_only
def test_compose_manual_append(compose_window, qapp):
    window, llm, _paste = compose_window
    window._config.compose_signature_text = "Best,\nTim"
    window.txtOutput.setPlainText("Hello world")
    window._append_variant("Hello world")
    window._sync_state()

    # Simulate button click
    window.btnSignature.click()

    assert window.txtOutput.toPlainText() == "Hello world\n\nBest,\nTim"
    assert window._variants[window._variant_index] == "Hello world\n\nBest,\nTim"


@gui_only
def test_compose_double_append_prevention(compose_window, qapp):
    window, llm, _paste = compose_window
    window._config.compose_signature_text = "Best,\nTim"
    window.txtOutput.setPlainText("Hello world\n\nBest,\nTim")
    window._append_variant("Hello world\n\nBest,\nTim")
    window._sync_state()

    # Sync state will disable the button if it ends with the signature
    window._sync_state()
    assert window.btnSignature.isEnabled() is False

    # Clicking it shouldn't append anything
    window.btnSignature.click()
    assert window.txtOutput.toPlainText() == "Hello world\n\nBest,\nTim"


@gui_only
def test_compose_auto_append(compose_window, qapp):
    window, llm, _paste = compose_window
    window._config.compose_signature_text = "Best,\nTim"
    window._config.compose_signature_auto_append = True

    window.txtInput.setPlainText("Hallo Welt")
    window.btnAction.click()

    _wait_until(
        qapp,
        lambda: not window._busy and window._worker_thread is None,
    )

    # Result from fake LLM is "OK", so it should auto-append
    assert window.txtOutput.toPlainText() == "OK\n\nBest,\nTim"
    assert window._variants[window._variant_index] == "OK\n\nBest,\nTim"


@gui_only
def test_compose_empty_signature_noop(compose_window, qapp):
    window, llm, _paste = compose_window
    window._config.compose_signature_text = "   "
    window._config.compose_signature_auto_append = True

    window.txtOutput.setPlainText("Hello")
    window._append_variant("Hello")
    window._sync_state()
    window._sync_state()

    assert window.btnSignature.isVisible() is False

    # Even if clicked manually
    window.btnSignature.click()
    assert window.txtOutput.toPlainText() == "Hello"


@gui_only
def test_compose_signature_replaces_german_placeholder(compose_window, qapp):
    window, _llm, _paste = compose_window
    window._config.compose_signature_text = "Tim Baumann"
    body = "Vielen Dank.\n\nMit freundlichen Grüßen,\n[Ihr Name]"
    window._append_variant(body)
    window._sync_state()

    window.btnSignature.click()

    expected = "Vielen Dank.\n\nMit freundlichen Grüßen,\nTim Baumann"
    assert window.txtOutput.toPlainText() == expected
    assert window._variants[window._variant_index] == expected


@gui_only
def test_compose_signature_replaces_placeholder_trailing_comma(compose_window, qapp):
    window, _llm, _paste = compose_window
    window._config.compose_signature_text = "Tim Baumann"
    window._append_variant("Grüße,\n[Dein Name],")
    window._sync_state()

    window.btnSignature.click()

    # The dangling comma after the placeholder is swallowed.
    assert window.txtOutput.toPlainText() == "Grüße,\nTim Baumann"


@gui_only
def test_compose_signature_replaces_english_placeholder(compose_window, qapp):
    window, _llm, _paste = compose_window
    window._config.compose_signature_text = "Tim Baumann"
    window._append_variant("Best regards,\n[Your Name]")
    window._sync_state()

    window.btnSignature.click()

    # English placeholder is replaced, not left behind with a second signature.
    assert window.txtOutput.toPlainText() == "Best regards,\nTim Baumann"


@gui_only
def test_compose_signature_replaces_vorname_placeholder(compose_window, qapp):
    window, _llm, _paste = compose_window
    window._config.compose_signature_text = "Tim"
    window._append_variant("Liebe Grüße\n[Dein Vorname]")
    window._sync_state()

    window.btnSignature.click()

    assert window.txtOutput.toPlainText() == "Liebe Grüße\nTim"


@gui_only
def test_compose_signature_no_double_after_placeholder(compose_window, qapp):
    window, _llm, _paste = compose_window
    window._config.compose_signature_text = "Tim Baumann"
    window._append_variant("Mit freundlichen Grüßen,\n[Ihr Name]")
    window._sync_state()

    window.btnSignature.click()
    # After replacement the signature is in place; the button must disable
    # and a second click must not append a duplicate signature.
    window._sync_state()
    assert window.btnSignature.isEnabled() is False
    window.btnSignature.click()
    assert window.txtOutput.toPlainText() == "Mit freundlichen Grüßen,\nTim Baumann"


@gui_only
def test_compose_signature_strips_saved_whitespace(compose_window, qapp):
    window, _llm, _paste = compose_window
    # Signature saved with accidental trailing newline/tab.
    window._config.compose_signature_text = "Tim Baumann\t\n"
    window._append_variant("Hallo")
    window._sync_state()

    window.btnSignature.click()

    assert window.txtOutput.toPlainText() == "Hallo\n\nTim Baumann"


@gui_only
def test_compose_signature_leaves_unrelated_brackets(compose_window, qapp):
    window, _llm, _paste = compose_window
    window._config.compose_signature_text = "Tim Baumann"
    window._append_variant("Siehe [Anhang] und [Datum].")
    window._sync_state()

    window.btnSignature.click()

    # Unrelated bracketed tokens are never treated as a signature placeholder.
    assert window.txtOutput.toPlainText() == "Siehe [Anhang] und [Datum].\n\nTim Baumann"


# --- Paket J: Tonfall-Selektor & Eigene Vorlage im Compose-Fenster ----------

from app.compose_window import COMPOSE_CUSTOM_PRESET_KEY  # noqa: E402


def _select_workflow(window, workflow: WorkflowType) -> None:
    window.cmbWorkflow.setCurrentIndex(window.cmbWorkflow.findData(workflow))


def _select_preset(window, preset_key: str) -> None:
    window.cmbPreset.setCurrentIndex(window.cmbPreset.findData(preset_key))


@gui_only
def test_tone_selector_visible_and_enabled_for_standard(qapp):
    window = ComposeWindow(_FakeLLMService(), _FakePasteService(), Config())
    window.show()
    qapp.processEvents()
    try:
        _select_workflow(window, WorkflowType.TEXT_IMPROVER)
        _select_preset(window, "standard")
        qapp.processEvents()
        assert window.cmbTone.isVisible() is True
        assert window.cmbTone.isEnabled() is True
    finally:
        window.close()
        qapp.processEvents()


@gui_only
def test_tone_selector_disabled_for_nonstandard_preset(qapp):
    window = ComposeWindow(_FakeLLMService(), _FakePasteService(), Config())
    window.show()
    qapp.processEvents()
    try:
        _select_workflow(window, WorkflowType.TEXT_IMPROVER)
        _select_preset(window, "email_formal")
        qapp.processEvents()
        assert window.cmbTone.isVisible() is True
        assert window.cmbTone.isEnabled() is False
        assert window.cmbTone.toolTip() == t("compose.tone.tooltip_preset_overrides")
    finally:
        window.close()
        qapp.processEvents()


@gui_only
def test_tone_selector_disabled_for_custom_preset(qapp):
    window = ComposeWindow(_FakeLLMService(), _FakePasteService(), Config())
    window.show()
    qapp.processEvents()
    try:
        _select_workflow(window, WorkflowType.TEXT_IMPROVER)
        _select_preset(window, COMPOSE_CUSTOM_PRESET_KEY)
        qapp.processEvents()
        assert window.cmbTone.isVisible() is True
        assert window.cmbTone.isEnabled() is False
    finally:
        window.close()
        qapp.processEvents()


@gui_only
@pytest.mark.parametrize("workflow", [WorkflowType.DAMPF_ABLASSEN, WorkflowType.EMOJI_TEXT])
def test_tone_selector_hidden_for_non_text_improver(qapp, workflow):
    window = ComposeWindow(_FakeLLMService(), _FakePasteService(), Config())
    window.show()
    qapp.processEvents()
    try:
        _select_workflow(window, workflow)
        qapp.processEvents()
        assert window.cmbTone.isVisible() is False
        assert window.lblTone.isVisible() is False
    finally:
        window.close()
        qapp.processEvents()


@gui_only
def test_tone_default_comes_from_config(qapp):
    config = Config()
    config.text_improver_tone = "formal"
    window = ComposeWindow(_FakeLLMService(), _FakePasteService(), config)
    try:
        assert window.cmbTone.currentData() == "formal"
    finally:
        window.close()
        qapp.processEvents()


@gui_only
def test_tone_labels_show_professionell_not_formal(qapp):
    window = ComposeWindow(_FakeLLMService(), _FakePasteService(), Config())
    try:
        labels = [window.cmbTone.itemText(i) for i in range(window.cmbTone.count())]
        assert "professionell" in labels
        assert "formal" not in labels
        # Internal value stays "formal" for backward compatibility.
        idx = window.cmbTone.findText("professionell")
        assert window.cmbTone.itemData(idx) == "formal"
    finally:
        window.close()
        qapp.processEvents()


@gui_only
def test_selected_tone_is_passed_to_worker(qapp):
    llm = _FakeLLMService()
    window = ComposeWindow(llm, _FakePasteService(), Config())
    window.show()
    qapp.processEvents()
    try:
        _select_workflow(window, WorkflowType.TEXT_IMPROVER)
        _select_preset(window, "standard")
        window.cmbTone.setCurrentIndex(window.cmbTone.findData("formal"))
        window.txtInput.setPlainText("Hallo Welt")
        window.btnAction.click()
        _wait_until(qapp, lambda: not window._busy and window._worker_thread is None and llm.calls)
        assert llm.last_tone == "formal"
        assert llm.last_custom_prompt is None
    finally:
        window.close()
        qapp.processEvents()


@gui_only
def test_custom_preset_passes_config_prompt_to_worker(qapp):
    config = Config()
    config.compose_custom_preset_text = "FREITEXT-PROMPT"
    llm = _FakeLLMService()
    window = ComposeWindow(llm, _FakePasteService(), config)
    window.show()
    qapp.processEvents()
    try:
        _select_workflow(window, WorkflowType.TEXT_IMPROVER)
        _select_preset(window, COMPOSE_CUSTOM_PRESET_KEY)
        window.txtInput.setPlainText("Hallo Welt")
        window.btnAction.click()
        _wait_until(qapp, lambda: not window._busy and window._worker_thread is None and llm.calls)
        # Base preset falls back to "standard"; the free prompt is plumbed separately.
        assert llm.calls[-1][2] == "standard"
        assert llm.last_custom_prompt == "FREITEXT-PROMPT"
    finally:
        window.close()
        qapp.processEvents()


@gui_only
def test_custom_preset_entry_present_in_combo(qapp):
    window = ComposeWindow(_FakeLLMService(), _FakePasteService(), Config())
    try:
        assert window.cmbPreset.findData(COMPOSE_CUSTOM_PRESET_KEY) >= 0
        idx = window.cmbPreset.findData(COMPOSE_CUSTOM_PRESET_KEY)
        assert window.cmbPreset.itemText(idx) == t("compose.preset.custom")
    finally:
        window.close()
        qapp.processEvents()


@gui_only
@pytest.mark.parametrize("language", ["de", "en"])
def test_tone_i18n_keys_present_and_complete(qapp, language):
    set_language(language)
    window = ComposeWindow(_FakeLLMService(), _FakePasteService(), Config())
    try:
        for key in (
            "compose.tone.label",
            "compose.tone.tooltip_active",
            "compose.tone.tooltip_preset_overrides",
            "compose.preset.custom",
            "tone.locker",
            "tone.neutral",
            "tone.formal",
        ):
            assert t(key) != key
        assert not missing_keys()
    finally:
        window.close()
        qapp.processEvents()

"""Tests für WorkflowType-Enum und Workflow-Metadaten."""
import pytest
from app.workflows import WorkflowType, WORKFLOW_META


class TestWorkflowType:
    def test_all_five_workflows_exist(self):
        expected = {"transcription", "local", "text_improver", "dampf_ablassen", "emoji_text"}
        assert {w.value for w in WorkflowType} == expected

    def test_transcription_no_llm(self):
        assert WORKFLOW_META[WorkflowType.TRANSCRIPTION]["needs_llm"] is False

    def test_local_no_llm(self):
        assert WORKFLOW_META[WorkflowType.LOCAL]["needs_llm"] is False

    def test_text_improver_needs_llm(self):
        assert WORKFLOW_META[WorkflowType.TEXT_IMPROVER]["needs_llm"] is True

    def test_dampf_ablassen_needs_llm(self):
        assert WORKFLOW_META[WorkflowType.DAMPF_ABLASSEN]["needs_llm"] is True

    def test_emoji_text_needs_llm(self):
        assert WORKFLOW_META[WorkflowType.EMOJI_TEXT]["needs_llm"] is True

    def test_hotkeys_defined(self):
        for wf in WorkflowType:
            assert "hotkey" in WORKFLOW_META[wf], f"Missing hotkey for {wf}"

    def test_transcription_hotkey(self):
        assert WORKFLOW_META[WorkflowType.TRANSCRIPTION]["hotkey"] == "Meta+H"

    def test_local_hotkey(self):
        assert WORKFLOW_META[WorkflowType.LOCAL]["hotkey"] == "Meta+Shift+H"

    def test_display_names_nonempty(self):
        for wf in WorkflowType:
            name = WORKFLOW_META[wf].get("display_name", "")
            assert name, f"Empty display_name for {wf}"

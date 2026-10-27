"""Tests für das WorkflowType-Enum."""
from app.workflows import WorkflowType


class TestWorkflowType:
    def test_all_five_workflows_exist(self):
        expected = {"transcription", "local", "text_improver", "dampf_ablassen", "emoji_text"}
        assert {w.value for w in WorkflowType} == expected

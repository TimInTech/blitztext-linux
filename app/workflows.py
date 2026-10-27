"""Workflow types for BlitztextLinux."""
from enum import Enum

class WorkflowType(str, Enum):
    TRANSCRIPTION = "transcription"
    LOCAL = "local"
    TEXT_IMPROVER = "text_improver"
    DAMPF_ABLASSEN = "dampf_ablassen"
    EMOJI_TEXT = "emoji_text"

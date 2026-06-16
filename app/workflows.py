"""Workflows configurations and metadata for BlitztextLinux."""
from enum import Enum
from typing import Dict, Any

class WorkflowType(str, Enum):
    TRANSCRIPTION = "transcription"
    LOCAL = "local"
    TEXT_IMPROVER = "text_improver"
    DAMPF_ABLASSEN = "dampf_ablassen"
    EMOJI_TEXT = "emoji_text"

WORKFLOW_META: Dict[WorkflowType, Dict[str, Any]] = {
    WorkflowType.TRANSCRIPTION: {
        "display_name": "🎙  Blitztext",
        "hotkey": "Meta+H",
        "needs_llm": False,
        "description": "Standard Sprache zu Text (Online oder Lokal)",
    },
    WorkflowType.LOCAL: {
        "display_name": "🔒  Blitztext Lokal",
        "hotkey": "Meta+Shift+H",
        "needs_llm": False,
        "description": "Lokale Sprache zu Text ohne Cloud",
    },
    WorkflowType.TEXT_IMPROVER: {
        "display_name": "✨  Blitztext+",
        "hotkey": "Meta+Shift+T",
        "needs_llm": True,
        "description": "Text verbessern und formatieren",
    },
    WorkflowType.DAMPF_ABLASSEN: {
        "display_name": "🔥  Blitztext $%&!",
        "hotkey": "Meta+Shift+D",
        "needs_llm": True,
        "description": "Frustrierte Sprache in professionelle Nachricht umwandeln",
    },
    WorkflowType.EMOJI_TEXT: {
        "display_name": "😊  Blitztext :)",
        "hotkey": "Meta+Shift+E",
        "needs_llm": True,
        "description": "Passende Emojis in Text einfügen",
    },
}

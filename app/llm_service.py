"""LLM service for BlitztextLinux rewrite workflows."""
from __future__ import annotations

import logging
from typing import Any, Optional

from app.workflows import WorkflowType
from app.writing_presets import DEFAULT_PRESET_KEY, get_preset

logger = logging.getLogger("blitztext.llm_service")

LLM_WORKFLOWS = {WorkflowType.TEXT_IMPROVER, WorkflowType.DAMPF_ABLASSEN, WorkflowType.EMOJI_TEXT}
MODEL = "gpt-4o-mini"

_DAMPF_SYSTEM = (
    "Du erhältst ein emotional gesprochenes Transkript. Erkenne zuerst das eigentliche "
    "Ziel, Anliegen und den wahren Frust der Person. Formuliere daraus eine klare, "
    "respektvolle und wirksame Nachricht, mit der die Person ihr Ziel eher erreicht. "
    "Bewahre relevante Fakten, konkrete Probleme, Grenzen, Erwartungen und die nötige "
    "Dringlichkeit. Entferne Beleidigungen, Drohungen, Sarkasmus, Unterstellungen und "
    "unnötige Eskalation. Wenn mehrere Vorwürfe genannt werden, verdichte sie auf die "
    "entscheidenden Kernpunkte. Der Ton soll ruhig, menschlich, bestimmt und "
    "lösungsorientiert sein. Gib NUR die fertige Nachricht zurück."
)

_TEXT_IMPROVER_SYSTEM_TEMPLATE = (
    "Du erhältst ein gesprochenes Transkript. Formuliere es zu einem sauberen, "
    "gut lesbaren Text um. Ton: {tone}. Behalte den Inhalt vollständig. "
    "Korrigiere Grammatik, Zeichensetzung und Struktur. Gib NUR den fertigen Text zurück."
)

_EMOJI_SYSTEM_TEMPLATE = (
    "Du erhältst einen Text. Füge passende Emojis ein. Emoji-Dichte: {density} "
    "(wenig = 1-2 pro Absatz, mittel = 3-5 pro Absatz, viel = 6+ pro Absatz). "
    "Gib NUR den Text mit Emojis zurück."
)


class LLMServiceError(Exception):
    """Raised when an LLM call fails."""


class LLMService:
    """Wraps OpenAI API calls for BlitztextLinux rewrite workflows."""

    def __init__(
        self,
        api_key: str = "",
        client: Optional[Any] = None,
        tone: str = "neutral",
        emoji_density: str = "mittel",
        dampf_system_prompt: str = "",
        custom_terms: Optional[list[str]] = None,
        api_key_env: str = "OPENAI_API_KEY",
        writing_preset: str = DEFAULT_PRESET_KEY,
    ) -> None:
        self.api_key = api_key or ""
        self.api_key_env = api_key_env or "OPENAI_API_KEY"
        self.tone = tone
        self.emoji_density = emoji_density
        self.dampf_system_prompt = dampf_system_prompt
        self.custom_terms = self._sanitize_terms(custom_terms)
        self.writing_preset = writing_preset or DEFAULT_PRESET_KEY

        self._openai_installed = True
        self._client_is_fallback_mock = False
        if client is not None:
            self.client = client
        else:
            try:
                import openai
            except ImportError:
                self._openai_installed = False
                self._client_is_fallback_mock = True
                from unittest.mock import MagicMock

                self.client = MagicMock()
            else:
                if self.api_key and self.api_key.strip():
                    self.client = openai.OpenAI(api_key=self.api_key)
                else:
                    # Ohne API-Key keinen echten Client bauen: Neuere openai-Versionen
                    # werfen bereits im Konstruktor bei leerem Key. Der eigentliche
                    # Fehler wird zur Aufrufzeit über _check_openai() klar gemeldet,
                    # damit die App auch ohne gesetzten Key startet.
                    from unittest.mock import MagicMock

                    self.client = MagicMock()

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def _missing_key_message(self) -> str:
        return (
            f"OpenAI API-Key nicht gesetzt. Bitte die Umgebungsvariable "
            f"{self.api_key_env} in ~/.config/blitztext-linux/secrets.env setzen."
        )

    def _check_openai(self) -> None:
        if not self.is_available():
            raise LLMServiceError(self._missing_key_message())
        if not self._openai_installed and self._client_is_fallback_mock:
            raise LLMServiceError("openai-Paket nicht installiert. Bitte: pip install openai")

    @staticmethod
    def _sanitize_terms(values: Optional[list[str]]) -> list[str]:
        if not values:
            return []
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str):
                continue
            term = value.strip()
            if not term or term in seen:
                continue
            seen.add(term)
            result.append(term)
        return result

    def _custom_terms_instruction(self) -> str:
        terms = self._sanitize_terms(self.custom_terms)
        if not terms:
            return ""
        return (
            "\n\nWichtig: Diese Eigennamen und Fachbegriffe muessen exakt so geschrieben werden: "
            + ", ".join(terms)
        )

    def dampf_ablassen(self, transcript: str, custom_system_prompt: str = "") -> str:
        self._check_openai()
        if not transcript or not transcript.strip():
            raise ValueError("transcript must not be empty")

        system = (custom_system_prompt.strip() or self.dampf_system_prompt.strip() or _DAMPF_SYSTEM) + self._custom_terms_instruction()

        response = self.client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": transcript.strip()},
            ],
            temperature=0.7,
        )
        content = response.choices[0].message.content
        if content is None:
            raise LLMServiceError("OpenAI hat eine leere Antwort zurückgegeben.")
        return content.strip()

    def text_improver(self, transcript: str, tone: str = "neutral", custom_prompt: str = "") -> str:
        self._check_openai()
        if not transcript or not transcript.strip():
            raise ValueError("transcript must not be empty")
        if tone not in {"formal", "neutral", "locker"}:
            raise ValueError(f"invalid tone: {tone}")

        system = (custom_prompt.strip() or _TEXT_IMPROVER_SYSTEM_TEMPLATE.format(tone=tone)) + self._custom_terms_instruction()

        response = self.client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": transcript.strip()},
            ],
            temperature=0.7,
        )
        content = response.choices[0].message.content
        if content is None:
            raise LLMServiceError("OpenAI hat eine leere Antwort zurückgegeben.")
        return content.strip()

    def emoji_text(self, transcript: str, density: str = "mittel") -> str:
        self._check_openai()
        if not transcript or not transcript.strip():
            raise ValueError("transcript must not be empty")
        if density not in {"wenig", "mittel", "viel"}:
            raise ValueError(f"invalid density: {density}")

        system = _EMOJI_SYSTEM_TEMPLATE.format(density=density) + self._custom_terms_instruction()

        response = self.client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": transcript.strip()},
            ],
            temperature=0.7,
        )
        content = response.choices[0].message.content
        if content is None:
            raise LLMServiceError("OpenAI hat eine leere Antwort zurückgegeben.")
        return content.strip()

    def rewrite(self, workflow: WorkflowType, transcript: str) -> str:
        """Send transcript to OpenAI and return the rewritten text.

        Raises:
            LLMServiceError: If key is missing, package missing, or API error.
        """
        self._check_openai()
        if workflow not in LLM_WORKFLOWS:
            raise LLMServiceError(f"rewrite() only allowed for LLM workflows, got {workflow!r}")

        try:
            if workflow == WorkflowType.DAMPF_ABLASSEN:
                return self.dampf_ablassen(transcript, custom_system_prompt=self.dampf_system_prompt)
            if workflow == WorkflowType.TEXT_IMPROVER:
                preset = get_preset(self.writing_preset)
                return self.text_improver(transcript, tone=self.tone, custom_prompt=preset.system_prompt)
            if workflow == WorkflowType.EMOJI_TEXT:
                return self.emoji_text(transcript, density=self.emoji_density)
            raise LLMServiceError(f"Unsupported workflow: {workflow}")
        except Exception as exc:
            if isinstance(exc, LLMServiceError):
                raise
            raise LLMServiceError(f"OpenAI API-Fehler: {exc}") from exc

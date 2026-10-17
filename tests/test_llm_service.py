"""Tests für LLMService — ohne echte Secrets oder Netzwerkzugriffe."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.config import DEFAULTS
from app.llm_service import (
    LLM_MAX_RETRIES,
    LLM_REQUEST_TIMEOUT,
    LLMService,
    LLMServiceError,
    _NullLLMClient,
    sanitize_external_error,
)
from app.workflows import WorkflowType
from app.writing_presets import WRITING_PRESETS


DUMMY_API_KEY = "dummy-openai-key"
RAW_TRANSCRIPT = "Ich bin total genervt von diesem Projekt und alles ist kaputt!"
CUSTOM_TERMS = ["Blitztext", "OpenRouter", "Leopoldshöhe"]


@pytest.fixture
def mock_client():
    client = MagicMock()
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))])
    client.chat.completions.create.return_value = response
    return client


@pytest.fixture
def service(mock_client):
    return LLMService(api_key=DUMMY_API_KEY, client=mock_client)


# Konkreter Fehlerfall: Diese Diktat-Eingabe wurde früher als Meeting
# umgedeutet ("alle Teilnehmer", Moderationsanweisung) statt als
# Übergabe-Prompt für eine neue Arbeits-Session erhalten zu bleiben.
HANDOVER_TRANSCRIPT = (
    "Erstelle eine kurze Übergabe prompt damit der Plan in neuer Session ausgeführt wird"
)


class TestExternalErrorSanitizing:
    def test_sanitize_external_error_masks_secrets_and_normalizes_spacing(self):
        hostile_error = (
            "  request\x00 failed\tBearer DUMMY_BEARER_TOKEN_123456\n"
            "sk-DUMMYKEY1234567890\rapi_key=DUMMY_API_KEY_123456\x1f"
            "https://alice:dummy-password@example.invalid/v1  "
        )

        assert sanitize_external_error(hostile_error) == (
            "request failed Bearer [REDACTED] [REDACTED] api_key=[REDACTED] "
            "https://[REDACTED]@example.invalid/v1"
        )

    def test_sanitize_external_error_truncates_within_default_limit(self):
        result = sanitize_external_error("x" * 300)

        assert len(result) <= 240
        assert result.endswith("…")

    def test_sanitize_external_error_canonicalizes_hidden_characters_before_masking(self):
        hostile_error = (
            "Bearer\x00DUMMY_BEARER_TOKEN_123456 "
            "api_key\u200b=\u200bDUMMY_API_KEY_123456"
        )

        assert sanitize_external_error(hostile_error) == (
            "Bearer [REDACTED] api_key=[REDACTED]"
        )

    @pytest.mark.parametrize(
        ("hostile_error", "expected"),
        [
            (
                '{"api_key": "DUMMY_API_KEY_123456"}',
                '{"api_key":[REDACTED]}',
            ),
            (
                "postgresql://alice:dummy-password@example.invalid/db",
                "postgresql://[REDACTED]@example.invalid/db",
            ),
            (
                "https://:dummy-password@example.invalid/v1",
                "https://[REDACTED]@example.invalid/v1",
            ),
        ],
    )
    def test_sanitize_external_error_masks_common_secret_representations(
        self, hostile_error, expected
    ):
        assert sanitize_external_error(hostile_error) == expected

    @pytest.mark.parametrize(
        "message",
        [
            "Bearer status",
            "Unsupported locale sk-SK",
            "Provider returned 👨\u200d💻 error",
        ],
    )
    def test_sanitize_external_error_preserves_legitimate_non_secrets(self, message):
        assert sanitize_external_error(message) == message

    @pytest.mark.parametrize(
        "hostile_error",
        [
            "Bear\x00er DUMMY_BEARER_TOKEN_123456",
            "api\x00_key=DUMMY_API_KEY_123456",
            "Bear\u200der DUMMY_BEARER_TOKEN_123456",
            "api\u200d_key=DUMMY_API_KEY_123456",
            "postgresql\x00://user:dummy-password@example.invalid/db",
            "postgresql:/\x00/user:dummy-password@example.invalid/db",
            "postgresql://us\x00er:dummy-password@example.invalid/db",
        ],
    )
    def test_sanitize_external_error_replaces_control_obfuscated_secret_atoms(
        self, hostile_error
    ):
        assert sanitize_external_error(hostile_error) == "Unbekannter Fehler"

    @pytest.mark.parametrize(
        "hostile_error",
        [
            "Bearer\u200bDUMMY_BEARER_TOKEN_123456",
            "Bearer\u200dDUMMY_BEARER_TOKEN_123456",
        ],
    )
    def test_sanitize_external_error_replaces_format_obfuscated_bearer_delimiters(
        self, hostile_error
    ):
        assert sanitize_external_error(hostile_error) == "Unbekannter Fehler"


class TestLLMServiceInit:
    def test_empty_api_key_is_not_available(self, mock_client):
        service = LLMService(api_key="", client=mock_client, api_key_env="CUSTOM_OPENAI_KEY")
        assert service.is_available() is False

    def test_missing_key_message_mentions_env_name_without_value(self, mock_client):
        service = LLMService(api_key="", client=mock_client, api_key_env="CUSTOM_OPENAI_KEY")

        with pytest.raises(LLMServiceError) as exc:
            service.rewrite(WorkflowType.TEXT_IMPROVER, "test")

        message = str(exc.value)
        assert "CUSTOM_OPENAI_KEY" in message
        assert DUMMY_API_KEY not in message
        assert "sk-" not in message

    def test_custom_terms_are_stored(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, custom_terms=CUSTOM_TERMS)
        assert service.custom_terms == CUSTOM_TERMS


class TestProviderConfig:

    def test_empty_api_key_uses_null_client_instead_of_mock(self):
        fake_openai = MagicMock()
        with patch.dict("sys.modules", {"openai": fake_openai}):
            service = LLMService(api_key="", base_url="")
        assert isinstance(service.client, _NullLLMClient)

    def test_default_model_comes_from_config_defaults(self, service):
        assert service.model == DEFAULTS["llm_model"]

    def test_custom_model_is_used_in_requests(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, model="openai/gpt-4o")
        service.text_improver("text")
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert kwargs["model"] == "openai/gpt-4o"

    def test_empty_model_falls_back_to_config_default(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, model="")
        assert service.model == DEFAULTS["llm_model"]

    def test_base_url_stored_on_service(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, base_url="https://openrouter.ai/api/v1")
        assert service.base_url == "https://openrouter.ai/api/v1"

    def test_base_url_passed_to_openai_client(self):
        # openai wird in LLMService.__init__ lazy importiert; via sys.modules
        # injizieren wir einen Fake, damit der Test ohne echtes openai-Paket laeuft.
        fake_openai = MagicMock()
        with patch.dict("sys.modules", {"openai": fake_openai}):
            LLMService(api_key=DUMMY_API_KEY, base_url="https://openrouter.ai/api/v1")
        fake_openai.OpenAI.assert_called_once_with(
            api_key=DUMMY_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            max_retries=LLM_MAX_RETRIES,
        )

    def test_empty_base_url_uses_sdk_default(self):
        fake_openai = MagicMock()
        with patch.dict("sys.modules", {"openai": fake_openai}):
            LLMService(api_key=DUMMY_API_KEY, base_url="")
        fake_openai.OpenAI.assert_called_once_with(
            api_key=DUMMY_API_KEY, base_url=None, max_retries=LLM_MAX_RETRIES
        )

    def test_chat_completion_uses_bounded_timeout(self, service, mock_client):
        service.rewrite(WorkflowType.TEXT_IMPROVER, RAW_TRANSCRIPT)
        assert mock_client.chat.completions.create.call_args.kwargs["timeout"] == LLM_REQUEST_TIMEOUT


class TestDampfAblassen:
    def test_returns_string(self, service):
        result = service.dampf_ablassen(RAW_TRANSCRIPT)
        assert isinstance(result, str)
        assert result == "OK"

    def test_passes_transcript_in_user_message(self, service, mock_client):
        service.dampf_ablassen(RAW_TRANSCRIPT)
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        user_messages = [m for m in messages if m["role"] == "user"]
        assert any(RAW_TRANSCRIPT in m["content"] for m in user_messages)

    def test_system_prompt_contains_custom_terms_instruction(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, custom_terms=CUSTOM_TERMS)
        service.dampf_ablassen(RAW_TRANSCRIPT)
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        system_message = next(m["content"] for m in messages if m["role"] == "system")
        assert "muessen exakt so geschrieben werden" in system_message
        assert ", ".join(CUSTOM_TERMS) in system_message


class TestTextImprover:
    def test_invalid_tone_raises(self, service):
        with pytest.raises(ValueError, match="tone"):
            service.text_improver("text", tone="aggressiv")

    def test_custom_prompt_used(self, service, mock_client):
        custom = "Mein eigener Prompt:"
        service.text_improver("text", tone="neutral", custom_prompt=custom)
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        assert custom in " ".join(m["content"] for m in messages)


class TestEmojiText:
    @pytest.mark.parametrize("density", ["wenig", "mittel", "viel"])
    def test_valid_densities(self, service, density):
        result = service.emoji_text("Hallo Welt", density=density)
        assert result == "OK"

    def test_invalid_density_raises(self, service):
        with pytest.raises(ValueError, match="density"):
            service.emoji_text("text", density="extrem")


class TestRewrite:
    def test_rewrite_routes_to_text_improver(self, service):
        with patch.object(service, "text_improver", return_value="verbessert") as patched:
            result = service.rewrite(WorkflowType.TEXT_IMPROVER, "roh")
        patched.assert_called_once_with("roh", tone=service.tone, custom_prompt="")
        assert result == "verbessert"

    def test_rewrite_text_uses_override_preset_without_mutating_service(self, mock_client):
        service = LLMService(
            api_key=DUMMY_API_KEY,
            client=mock_client,
            writing_preset="standard",
        )

        result = service.rewrite_text(
            WorkflowType.TEXT_IMPROVER,
            RAW_TRANSCRIPT,
            writing_preset="shorten",
        )

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        system_message = next(m["content"] for m in messages if m["role"] == "system")
        assert result == "OK"
        assert WRITING_PRESETS["shorten"].system_prompt in system_message
        assert service.writing_preset == "standard"

    def test_openai_error_is_wrapped(self, service):
        with patch.object(service, "dampf_ablassen", side_effect=RuntimeError("API Error")):
            with pytest.raises(LLMServiceError, match="OpenAI API-Fehler: API Error"):
                service.rewrite(WorkflowType.DAMPF_ABLASSEN, RAW_TRANSCRIPT)

    def test_missing_openai_package_raises_clear_error(self, service):
        service._openai_installed = False
        service._client_is_fallback_mock = True

        with pytest.raises(LLMServiceError, match="openai-Paket nicht installiert"):
            service.rewrite(WorkflowType.TEXT_IMPROVER, "test")


class TestWritingPreset:
    def test_default_writing_preset_is_standard(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client)
        assert service.writing_preset == "standard"

    def test_standard_preset_keeps_default_text_improver_prompt(self, service, mock_client):
        service.rewrite(WorkflowType.TEXT_IMPROVER, RAW_TRANSCRIPT)
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        system_message = next(m["content"] for m in messages if m["role"] == "system")
        # Standard verwendet weiterhin das Default-Template (kein Preset-Prompt).
        assert "Du bist ein Lektor und Schreibassistent" in system_message
        for key, preset in WRITING_PRESETS.items():
            if key in {"standard", "custom"}:
                continue
            assert preset.system_prompt not in system_message

    def test_preset_prompt_is_passed_as_system_message(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, writing_preset="shorten")
        service.rewrite(WorkflowType.TEXT_IMPROVER, RAW_TRANSCRIPT)
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        system_message = next(m["content"] for m in messages if m["role"] == "system")
        assert WRITING_PRESETS["shorten"].system_prompt in system_message

    def test_unknown_preset_falls_back_to_standard_behavior(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, writing_preset="gibt-es-nicht")
        service.rewrite(WorkflowType.TEXT_IMPROVER, RAW_TRANSCRIPT)
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        system_message = next(m["content"] for m in messages if m["role"] == "system")
        assert "Du bist ein Lektor und Schreibassistent" in system_message

    def test_custom_terms_still_applied_with_preset(self, mock_client):
        service = LLMService(
            api_key=DUMMY_API_KEY,
            client=mock_client,
            writing_preset="shorten",
            custom_terms=CUSTOM_TERMS,
        )
        service.rewrite(WorkflowType.TEXT_IMPROVER, RAW_TRANSCRIPT)
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        system_message = next(m["content"] for m in messages if m["role"] == "system")
        assert WRITING_PRESETS["shorten"].system_prompt in system_message
        assert "muessen exakt so geschrieben werden" in system_message
        assert ", ".join(CUSTOM_TERMS) in system_message

    def test_transcript_stays_in_user_message_not_system(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, writing_preset="shorten")
        service.rewrite(WorkflowType.TEXT_IMPROVER, RAW_TRANSCRIPT)
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        system_message = next(m["content"] for m in messages if m["role"] == "system")
        user_message = next(m["content"] for m in messages if m["role"] == "user")
        assert RAW_TRANSCRIPT in user_message
        assert RAW_TRANSCRIPT not in system_message


class TestComposeTonePlumbing:
    """Paket J: tone- und custom_prompt-Durchreichung über rewrite_text."""

    def _system_message(self, mock_client):
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        return next(m["content"] for m in messages if m["role"] == "system")

    def test_tone_override_used_for_change_tone_action(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, tone="neutral")
        service.rewrite_text(
            WorkflowType.TEXT_IMPROVER,
            RAW_TRANSCRIPT,
            writing_preset="change_tone",
            tone="formal",
        )
        assert "Ziel-Tonfall: professionell und höflich" in self._system_message(mock_client)
        # Service-State bleibt unverändert (rückwärtskompatibel).
        assert service.tone == "neutral"

    def test_tone_none_falls_back_to_service_tone(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, tone="locker")
        service.rewrite_text(
            WorkflowType.TEXT_IMPROVER,
            RAW_TRANSCRIPT,
            writing_preset="change_tone",
            tone=None,
        )
        assert "Ziel-Tonfall: locker und freundlich" in self._system_message(mock_client)

    def test_custom_prompt_override_used_as_system(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client)
        service.rewrite_text(
            WorkflowType.TEXT_IMPROVER,
            RAW_TRANSCRIPT,
            writing_preset="standard",
            custom_prompt="Schreibe als sachliche Pressemitteilung.",
        )
        system_message = self._system_message(mock_client)
        assert "Schreibe als sachliche Pressemitteilung." in system_message
        assert "Du bist ein Lektor und Schreibassistent" not in system_message

    def test_empty_custom_prompt_falls_back_to_preset(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client)
        service.rewrite_text(
            WorkflowType.TEXT_IMPROVER,
            RAW_TRANSCRIPT,
            writing_preset="standard",
            custom_prompt="   ",
        )
        assert "Du bist ein Lektor und Schreibassistent" in self._system_message(mock_client)

    def test_custom_terms_still_applied_with_custom_prompt(self, mock_client):
        service = LLMService(
            api_key=DUMMY_API_KEY,
            client=mock_client,
            custom_terms=CUSTOM_TERMS,
        )
        service.rewrite_text(
            WorkflowType.TEXT_IMPROVER,
            RAW_TRANSCRIPT,
            custom_prompt="Freier Prompt.",
        )
        system_message = self._system_message(mock_client)
        assert "Freier Prompt." in system_message
        assert ", ".join(CUSTOM_TERMS) in system_message

    def test_standard_without_overrides_applies_saved_tone(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, tone="neutral")
        service.rewrite_text(WorkflowType.TEXT_IMPROVER, RAW_TRANSCRIPT)
        system = self._system_message(mock_client)
        assert "Verwende einen neutralen, klaren Ton" in system


class TestBuildSystemPrompt:
    """Paket J: build_system_prompt() gibt den aufgelösten Prompt zurück ohne API-Call."""

    def test_standard_preset_applies_saved_tone(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, tone="formal")
        prompt = service.build_system_prompt(WorkflowType.TEXT_IMPROVER, writing_preset="standard")
        assert "Verwende einen formellen, professionellen Ton" in prompt
        assert "Du bist ein Lektor und Schreibassistent" in prompt

    def test_tone_override_reflected_in_change_tone_prompt(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, tone="neutral")
        prompt = service.build_system_prompt(
            WorkflowType.TEXT_IMPROVER, writing_preset="change_tone", tone="locker"
        )
        assert "Ziel-Tonfall: locker und freundlich" in prompt

    def test_non_standard_preset_uses_preset_prompt(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client)
        prompt = service.build_system_prompt(WorkflowType.TEXT_IMPROVER, writing_preset="shorten")
        from app.writing_presets import WRITING_PRESETS
        assert WRITING_PRESETS["shorten"].system_prompt in prompt

    def test_custom_prompt_overrides_preset(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client)
        prompt = service.build_system_prompt(
            WorkflowType.TEXT_IMPROVER,
            writing_preset="shorten",
            custom_prompt="Schreibe als Pressemitteilung.",
        )
        assert "Schreibe als Pressemitteilung." in prompt
        from app.writing_presets import WRITING_PRESETS
        assert WRITING_PRESETS["shorten"].system_prompt not in prompt

    def test_empty_custom_prompt_falls_back_to_preset(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, tone="neutral")
        prompt = service.build_system_prompt(
            WorkflowType.TEXT_IMPROVER, writing_preset="standard", custom_prompt="   "
        )
        assert "Du bist ein Lektor und Schreibassistent" in prompt

    def test_custom_terms_appended(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, custom_terms=CUSTOM_TERMS)
        prompt = service.build_system_prompt(WorkflowType.TEXT_IMPROVER)
        assert ", ".join(CUSTOM_TERMS) in prompt

    def test_dampf_ablassen_uses_dampf_system(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client)
        prompt = service.build_system_prompt(WorkflowType.DAMPF_ABLASSEN)
        assert "respektvolle" in prompt

    def test_dampf_ablassen_custom_system_prompt_attribute(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, dampf_system_prompt="Mein Custom.")
        prompt = service.build_system_prompt(WorkflowType.DAMPF_ABLASSEN)
        assert "Mein Custom." in prompt

    def test_emoji_text_uses_density(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, emoji_density="viel")
        prompt = service.build_system_prompt(WorkflowType.EMOJI_TEXT)
        assert "viel" in prompt

    def test_no_api_call_made(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client)
        service.build_system_prompt(WorkflowType.TEXT_IMPROVER)
        mock_client.chat.completions.create.assert_not_called()

    def test_prompt_matches_actual_api_call(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, tone="neutral")
        preview = service.build_system_prompt(WorkflowType.TEXT_IMPROVER, writing_preset="standard")
        service.rewrite_text(WorkflowType.TEXT_IMPROVER, RAW_TRANSCRIPT, writing_preset="standard")
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        actual_system = next(m["content"] for m in messages if m["role"] == "system")
        assert preview == actual_system


class TestRewriteRaw:
    """Paket J: rewrite_raw() sendet die Prompts direkt ohne Preset-Logik."""

    def test_sends_provided_system_and_user_message(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client)
        service.rewrite_raw("Mein System-Prompt.", "Meine Nutzernachricht.")
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        messages = kwargs["messages"]
        assert messages[0] == {"role": "system", "content": "Mein System-Prompt."}
        assert messages[1] == {"role": "user", "content": "Meine Nutzernachricht."}

    def test_returns_api_response(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client)
        result = service.rewrite_raw("System.", "User.")
        assert result == "OK"

    def test_empty_user_message_raises(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client)
        with pytest.raises(ValueError, match="user_message"):
            service.rewrite_raw("System.", "   ")

    def test_no_custom_terms_added(self, mock_client):
        service = LLMService(
            api_key=DUMMY_API_KEY, client=mock_client, custom_terms=CUSTOM_TERMS
        )
        service.rewrite_raw("System.", "User.")
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        system = next(m["content"] for m in kwargs["messages"] if m["role"] == "system")
        assert "muessen exakt so geschrieben werden" not in system

    def test_api_error_wrapped_as_llm_service_error(self, mock_client):
        mock_client.chat.completions.create.side_effect = RuntimeError("Verbindungsfehler")
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client)
        with pytest.raises(LLMServiceError, match="OpenAI API-Fehler"):
            service.rewrite_raw("System.", "User.")

    def test_unavailable_service_raises(self, mock_client):
        service = LLMService(api_key="", client=mock_client)
        with pytest.raises(LLMServiceError):
            service.rewrite_raw("System.", "User.")


class TestIntentPreservationRegression:
    """Regression: Übergabe-/Prompt-Aufträge dürfen nicht als Meeting umgedeutet werden.

    Die Tests laufen ohne echtes LLM. Geprüft wird der Prompt-Vertrag: Die
    Schutzregeln müssen im System-Prompt ankommen und das Original-Transkript
    muss unverändert als User-Message übertragen werden.
    """

    def _messages(self, mock_client):
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        system = next(m["content"] for m in kwargs["messages"] if m["role"] == "system")
        user = next(m["content"] for m in kwargs["messages"] if m["role"] == "user")
        return system, user

    def test_standard_preset_system_prompt_contains_intent_rules(self, service, mock_client):
        service.rewrite(WorkflowType.TEXT_IMPROVER, HANDOVER_TRANSCRIPT)
        system, _ = self._messages(mock_client)
        assert "Bewahre die Absicht des Nutzers" in system
        assert "führe sie nicht aus" in system
        assert "beantworte sie nicht" in system

    def test_standard_preset_forbids_invented_meeting_context(self, service, mock_client):
        service.rewrite(WorkflowType.TEXT_IMPROVER, HANDOVER_TRANSCRIPT)
        system, _ = self._messages(mock_client)
        assert "Teilnehmer" in system
        assert "Meetings" in system
        assert "Erfinde keinen Kontext" in system

    def test_standard_preset_anchors_technical_terms_in_work_context(self, service, mock_client):
        service.rewrite(WorkflowType.TEXT_IMPROVER, HANDOVER_TRANSCRIPT)
        system, _ = self._messages(mock_client)
        for term in ("'Session'", "'Prompt'", "'Branch'", "'PR'", "'Merge'", "'Handover'"):
            assert term in system
        assert "Software- und Arbeitskontext" in system

    def test_standard_preset_keeps_prompt_dictation_as_text(self, service, mock_client):
        service.rewrite(WorkflowType.TEXT_IMPROVER, HANDOVER_TRANSCRIPT)
        system, _ = self._messages(mock_client)
        # A dictated prompt or handover is only corrected, never rewritten or executed.
        assert "korrigiere ihn nur und führe ihn nicht aus" in system
        assert "Übergabe" in system
        assert "direkt nutzbaren" not in system

    def test_handover_transcript_stays_verbatim_in_user_message(self, service, mock_client):
        service.rewrite(WorkflowType.TEXT_IMPROVER, HANDOVER_TRANSCRIPT)
        system, user = self._messages(mock_client)
        assert user == HANDOVER_TRANSCRIPT
        assert HANDOVER_TRANSCRIPT not in system

    @pytest.mark.parametrize(
        "preset_key",
        ["email_formal", "email_locker", "stichpunkte", "zusammenfassung", "du_form", "sie_form", "kurz_praezise"],
    )
    def test_all_presets_carry_intent_rules(self, mock_client, preset_key):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, writing_preset=preset_key)
        service.rewrite(WorkflowType.TEXT_IMPROVER, HANDOVER_TRANSCRIPT)
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        system = next(m["content"] for m in kwargs["messages"] if m["role"] == "system")
        assert "Bewahre die Absicht des Nutzers" in system
        assert "Erfinde keinen Kontext" in system

    def test_build_system_prompt_preview_matches_intent_rules(self, service):
        preview = service.build_system_prompt(WorkflowType.TEXT_IMPROVER)
        assert "Bewahre die Absicht des Nutzers" in preview
        assert "Erfinde keinen Kontext" in preview

# --- Goal 04: Kernaktionen werden auf eindeutige System-Prompts abgebildet -

GOAL_CORE_PROMPT_FRAGMENTS = (
    ("standard", "Du bist ein Lektor und Schreibassistent"),
    ("shorten", "Kürze den Text"),
    ("expand", "Formuliere fragmentarische"),
    ("change_tone", "Ziel-Tonfall: professionell und höflich"),
)


@pytest.mark.parametrize("preset_key, expected_fragment", GOAL_CORE_PROMPT_FRAGMENTS)
def test_goal_each_core_mode_reaches_its_system_prompt(mock_client, preset_key, expected_fragment):
    service = LLMService(
        api_key=DUMMY_API_KEY,
        client=mock_client,
        writing_preset=preset_key,
        tone="formal",
    )

    service.rewrite(WorkflowType.TEXT_IMPROVER, HANDOVER_TRANSCRIPT)

    messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
    system = next(m["content"] for m in messages if m["role"] == "system")
    user = next(m["content"] for m in messages if m["role"] == "user")
    assert expected_fragment in system
    assert "Antworte in derselben Sprache" in system
    assert "führe sie nicht aus" in system
    assert "beantworte sie nicht" in system
    assert "Erfinde keinen Kontext" in system
    assert user == HANDOVER_TRANSCRIPT


@pytest.mark.parametrize(
    "legacy, expected_fragment",
    [
        ("standard", "Du bist ein Lektor und Schreibassistent"),
        ("email_formal", "Ziel-Tonfall: professionell und höflich"),
        ("email_locker", "Ziel-Tonfall: locker und freundlich"),
        ("stichpunkte", "Kürze den Text"),
        ("zusammenfassung", "Kürze den Text"),
        ("du_form", "Ziel-Tonfall: locker und freundlich"),
        ("sie_form", "Ziel-Tonfall: professionell und höflich"),
        ("kurz_praezise", "Kürze den Text"),
    ],
)
def test_goal_legacy_service_values_resolve_to_canonical_prompts(
    mock_client, legacy, expected_fragment
):
    service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, writing_preset=legacy)
    prompt = service.build_system_prompt(WorkflowType.TEXT_IMPROVER)
    assert expected_fragment in prompt


def test_goal_custom_action_uses_existing_user_prompt_verbatim(mock_client):
    custom_prompt = "  Mein eigener System-Prompt bleibt unverändert.  \n"
    service = LLMService(
        api_key=DUMMY_API_KEY,
        client=mock_client,
        writing_preset="custom",
        writing_custom_prompt=custom_prompt,
    )

    service.rewrite(WorkflowType.TEXT_IMPROVER, RAW_TRANSCRIPT)

    messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
    system = next(m["content"] for m in messages if m["role"] == "system")
    assert system == custom_prompt.strip()


def test_goal_blank_custom_action_falls_back_to_safe_standard_prompt(mock_client):
    service = LLMService(
        api_key=DUMMY_API_KEY,
        client=mock_client,
        writing_preset="custom",
        writing_custom_prompt="   ",
    )
    prompt = service.build_system_prompt(WorkflowType.TEXT_IMPROVER)
    assert "Du bist ein Lektor und Schreibassistent" in prompt
    assert "Antworte in derselben Sprache" in prompt


# --- Goal 04: gespeicherter Standard-Tonfall bleibt wirksam -------------


def test_goal_loaded_standard_keeps_saved_formal_tone_effect(tmp_path, mock_client):
    import json
    from app.config import BlitztextConfig

    config_dir = tmp_path / ".config" / "blitztext-linux"
    config_dir.mkdir(parents=True)
    (config_dir / "config.json").write_text(
        json.dumps(
            {
                "workflows": {
                    "writing_preset": "standard",
                    "text_improver_tone": "formal",
                }
            }
        ),
        encoding="utf-8",
    )
    loaded = BlitztextConfig(config_dir=config_dir)
    service = LLMService(
        api_key=DUMMY_API_KEY,
        client=mock_client,
        writing_preset=loaded.writing_preset,
        tone=loaded.text_improver_tone,
    )

    prompt = service.build_system_prompt(WorkflowType.TEXT_IMPROVER)

    assert loaded.writing_preset == "standard"
    assert loaded.text_improver_tone == "formal"
    assert "Verwende einen formellen, professionellen Ton" in prompt


class TestOriginalBlitztextParameters:
    """Sampling and prompt core follow the original Blitztext app (LLMService.swift)."""

    @pytest.mark.parametrize(
        ("workflow", "temperature"),
        [
            (WorkflowType.TEXT_IMPROVER, 0.3),
            (WorkflowType.EMOJI_TEXT, 0.3),
            (WorkflowType.DAMPF_ABLASSEN, 0.4),
        ],
    )
    def test_workflow_temperature(self, service, mock_client, workflow, temperature):
        service.rewrite(workflow, RAW_TRANSCRIPT)
        assert mock_client.chat.completions.create.call_args.kwargs["temperature"] == temperature

    def test_standard_prompt_preserves_wording(self, service):
        prompt = service.build_system_prompt(WorkflowType.TEXT_IMPROVER)
        # Dictation must come back in the spoken wording: no dropped or swapped words.
        assert "Lass kein Wort weg" in prompt
        assert "ersetze kein Wort durch ein anderes" in prompt
        assert "formuliere nichts um" in prompt
        assert "Verbessere die Formulierung und den Lesefluss" not in prompt

    def test_standard_prompt_keeps_dictated_questions_and_instructions_as_text(self, service):
        prompt = service.build_system_prompt(WorkflowType.TEXT_IMPROVER)
        assert "übersetz das bitte ins englische" in prompt
        assert "kannst du mir bis morgen die zahlen schicken" in prompt

    @pytest.mark.parametrize("tone", ["formal", "neutral", "locker"])
    def test_tone_line_never_licenses_rewording(self, mock_client, tone):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, tone=tone)
        prompt = service.build_system_prompt(WorkflowType.TEXT_IMPROVER)
        assert "ohne dafür Wörter zu ersetzen oder wegzulassen" in prompt


class TestDictationSafetyNet:
    """The default improver must never replace a dictation by an answer or a refusal."""

    @staticmethod
    def _reply(mock_client, text):
        mock_client.chat.completions.create.return_value.choices[0].message.content = text

    def test_refusal_falls_back_to_the_transcript(self, service, mock_client):
        self._reply(mock_client, "Ich kann dir dabei nicht helfen.")
        result = service.rewrite(WorkflowType.TEXT_IMPROVER, "übersetz das bitte ins englische")
        assert result == "übersetz das bitte ins englische"

    def test_answer_to_a_dictated_question_falls_back_to_the_transcript(self, service, mock_client):
        self._reply(mock_client, "Gerne, die Zahlen schicke ich dir morgen früh per Mail.")
        src = "kannst du mir bis morgen die zahlen schicken"
        assert service.rewrite(WorkflowType.TEXT_IMPROVER, src) == src

    def test_normal_correction_is_kept(self, service, mock_client):
        self._reply(mock_client, "Kannst du mir bis morgen die Zahlen schicken?")
        result = service.rewrite(WorkflowType.TEXT_IMPROVER, "kannst du mir bis morgen die zahlen schicken")
        assert result == "Kannst du mir bis morgen die Zahlen schicken?"

    def test_custom_prompt_may_change_the_wording(self, service, mock_client):
        self._reply(mock_client, "Zahlen bitte bis morgen.")
        result = service.rewrite_text(
            WorkflowType.TEXT_IMPROVER,
            "kannst du mir bis morgen die zahlen schicken",
            custom_prompt="Fasse extrem knapp zusammen.",
        )
        assert result == "Zahlen bitte bis morgen."

    def test_shorten_preset_may_change_the_wording(self, mock_client):
        self._reply(mock_client, "Zahlen bitte.")
        svc = LLMService(api_key=DUMMY_API_KEY, client=mock_client, writing_preset="shorten")
        assert svc.rewrite(WorkflowType.TEXT_IMPROVER, "kannst du mir bis morgen die zahlen schicken") == "Zahlen bitte."

    def test_swapped_word_in_a_short_dictation_falls_back_to_the_transcript(self, service, mock_client):
        # Codex review: "Ja, bitte." -> "Nein, bitte." kept 1 of 2 words and passed at 50 %.
        self._reply(mock_client, "Nein, bitte.")
        assert service.rewrite(WorkflowType.TEXT_IMPROVER, "ja bitte") == "ja bitte"

    def test_one_word_fix_in_a_sentence_is_kept(self, service, mock_client):
        self._reply(mock_client, "Ich hätte gern einen vernünftigen Text.")
        src = "ich hätte gern ein vernünftigen text"
        assert service.rewrite(WorkflowType.TEXT_IMPROVER, src) == "Ich hätte gern einen vernünftigen Text."

    def test_das_dass_fix_counts_as_the_same_word(self, service, mock_client):
        # "das" -> "dass" is a correction the prompt asks for, not a lost word.
        self._reply(mock_client, "Dass")
        assert service.rewrite(WorkflowType.TEXT_IMPROVER, "das") == "Dass"

"""Tests für LLMService — ohne echte Secrets oder Netzwerkzugriffe."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.llm_service import LLMService, LLMServiceError
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
        assert "Formuliere es zu einem sauberen" in system_message
        for key, preset in WRITING_PRESETS.items():
            if key == "standard":
                continue
            assert preset.system_prompt not in system_message

    def test_preset_prompt_is_passed_as_system_message(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, writing_preset="email_formal")
        service.rewrite(WorkflowType.TEXT_IMPROVER, RAW_TRANSCRIPT)
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        system_message = next(m["content"] for m in messages if m["role"] == "system")
        assert WRITING_PRESETS["email_formal"].system_prompt in system_message

    def test_unknown_preset_falls_back_to_standard_behavior(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, writing_preset="gibt-es-nicht")
        service.rewrite(WorkflowType.TEXT_IMPROVER, RAW_TRANSCRIPT)
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        system_message = next(m["content"] for m in messages if m["role"] == "system")
        assert "Formuliere es zu einem sauberen" in system_message

    def test_custom_terms_still_applied_with_preset(self, mock_client):
        service = LLMService(
            api_key=DUMMY_API_KEY,
            client=mock_client,
            writing_preset="stichpunkte",
            custom_terms=CUSTOM_TERMS,
        )
        service.rewrite(WorkflowType.TEXT_IMPROVER, RAW_TRANSCRIPT)
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        system_message = next(m["content"] for m in messages if m["role"] == "system")
        assert WRITING_PRESETS["stichpunkte"].system_prompt in system_message
        assert "muessen exakt so geschrieben werden" in system_message
        assert ", ".join(CUSTOM_TERMS) in system_message

    def test_transcript_stays_in_user_message_not_system(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, writing_preset="email_formal")
        service.rewrite(WorkflowType.TEXT_IMPROVER, RAW_TRANSCRIPT)
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        system_message = next(m["content"] for m in messages if m["role"] == "system")
        user_message = next(m["content"] for m in messages if m["role"] == "user")
        assert RAW_TRANSCRIPT in user_message
        assert RAW_TRANSCRIPT not in system_message

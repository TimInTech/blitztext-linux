"""Tests für LLMService — ohne echte Secrets oder Netzwerkzugriffe."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.config import DEFAULTS
from app.llm_service import LLMService, LLMServiceError, _NullLLMClient
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
            api_key=DUMMY_API_KEY, base_url="https://openrouter.ai/api/v1"
        )

    def test_empty_base_url_uses_sdk_default(self):
        fake_openai = MagicMock()
        with patch.dict("sys.modules", {"openai": fake_openai}):
            LLMService(api_key=DUMMY_API_KEY, base_url="")
        fake_openai.OpenAI.assert_called_once_with(api_key=DUMMY_API_KEY, base_url=None)


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
            writing_preset="email_formal",
        )

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        system_message = next(m["content"] for m in messages if m["role"] == "system")
        assert result == "OK"
        assert WRITING_PRESETS["email_formal"].system_prompt in system_message
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


class TestComposeTonePlumbing:
    """Paket J: tone- und custom_prompt-Durchreichung über rewrite_text."""

    def _system_message(self, mock_client):
        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        return next(m["content"] for m in messages if m["role"] == "system")

    def test_tone_override_used_for_standard_preset(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, tone="neutral")
        service.rewrite_text(
            WorkflowType.TEXT_IMPROVER,
            RAW_TRANSCRIPT,
            writing_preset="standard",
            tone="formal",
        )
        assert "Ton: formal" in self._system_message(mock_client)
        # Service-State bleibt unverändert (rückwärtskompatibel).
        assert service.tone == "neutral"

    def test_tone_none_falls_back_to_service_tone(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, tone="locker")
        service.rewrite_text(
            WorkflowType.TEXT_IMPROVER,
            RAW_TRANSCRIPT,
            writing_preset="standard",
            tone=None,
        )
        assert "Ton: locker" in self._system_message(mock_client)

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
        assert "Formuliere es zu einem sauberen" not in system_message

    def test_empty_custom_prompt_falls_back_to_preset(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client)
        service.rewrite_text(
            WorkflowType.TEXT_IMPROVER,
            RAW_TRANSCRIPT,
            writing_preset="standard",
            custom_prompt="   ",
        )
        assert "Formuliere es zu einem sauberen" in self._system_message(mock_client)

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

    def test_tone_and_custom_prompt_default_none_keeps_legacy_behavior(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, tone="neutral")
        service.rewrite_text(WorkflowType.TEXT_IMPROVER, RAW_TRANSCRIPT)
        assert "Ton: neutral" in self._system_message(mock_client)


class TestBuildSystemPrompt:
    """Paket J: build_system_prompt() gibt den aufgelösten Prompt zurück ohne API-Call."""

    def test_standard_preset_with_tone_uses_template(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, tone="formal")
        prompt = service.build_system_prompt(WorkflowType.TEXT_IMPROVER, writing_preset="standard")
        assert "Ton: formal" in prompt
        assert "Formuliere es zu einem sauberen" in prompt

    def test_tone_override_reflected_in_prompt(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, tone="neutral")
        prompt = service.build_system_prompt(
            WorkflowType.TEXT_IMPROVER, writing_preset="standard", tone="locker"
        )
        assert "Ton: locker" in prompt

    def test_non_standard_preset_uses_preset_prompt(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client)
        prompt = service.build_system_prompt(WorkflowType.TEXT_IMPROVER, writing_preset="email_formal")
        from app.writing_presets import WRITING_PRESETS
        assert WRITING_PRESETS["email_formal"].system_prompt in prompt

    def test_custom_prompt_overrides_preset(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client)
        prompt = service.build_system_prompt(
            WorkflowType.TEXT_IMPROVER,
            writing_preset="email_formal",
            custom_prompt="Schreibe als Pressemitteilung.",
        )
        assert "Schreibe als Pressemitteilung." in prompt
        from app.writing_presets import WRITING_PRESETS
        assert WRITING_PRESETS["email_formal"].system_prompt not in prompt

    def test_empty_custom_prompt_falls_back_to_preset(self, mock_client):
        service = LLMService(api_key=DUMMY_API_KEY, client=mock_client, tone="neutral")
        prompt = service.build_system_prompt(
            WorkflowType.TEXT_IMPROVER, writing_preset="standard", custom_prompt="   "
        )
        assert "Formuliere es zu einem sauberen" in prompt

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

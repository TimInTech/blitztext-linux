"""Tests für BlitztextConfig — Defaults, Persistenz, Legacy-Migration."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from app.config import BlitztextConfig


@pytest.fixture
def config_dir(tmp_path) -> Path:
    return tmp_path / ".config" / "blitztext-linux"


@pytest.fixture
def config(config_dir) -> BlitztextConfig:
    return BlitztextConfig(config_dir=config_dir)


class TestDefaults:
    def test_default_model_is_base(self, config):
        assert config.model == "base"

    def test_default_language_is_de(self, config):
        assert config.language == "de"

    def test_default_backend_is_openai_whisper(self, config):
        assert config.backend == "openai-whisper"

    def test_default_hotkey_mode(self, config):
        assert config.hotkey_mode in ("toggle", "hold")

    def test_default_api_key_env(self, config):
        assert config.openai_api_key_env == "OPENAI_API_KEY"
        assert config.resolve_openai_api_key() == ""

    def test_default_autopaste(self, config):
        assert config.autopaste is True


class TestPersistence:
    def test_save_load_roundtrip(self, config, config_dir):
        config.model = "small"
        config.language = "en"
        config.openai_api_key_env = "my_openai_key"
        config.save()

        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.model == "small"
        assert loaded.language == "en"
        assert loaded.openai_api_key_env == "MY_OPENAI_KEY"

    def test_config_file_permissions(self, config, config_dir):
        config.save()
        mode = (config_dir / "config.json").stat().st_mode & 0o777
        assert mode == 0o600

    def test_partial_config_fills_defaults(self, config_dir):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(json.dumps({"model": "tiny"}), encoding="utf-8")

        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.model == "tiny"
        assert loaded.language == "de"
        assert loaded.openai_api_key_env == "OPENAI_API_KEY"


class TestWorkflowConfig:
    def test_workflows_dict_created_when_missing(self, config_dir):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(json.dumps({"model": "base"}), encoding="utf-8")

        loaded = BlitztextConfig(config_dir=config_dir)
        assert isinstance(loaded.workflows, dict)
        assert loaded.text_improver_tone == "neutral"
        assert loaded.emoji_density == "mittel"
        assert loaded.custom_terms == []

    def test_custom_terms_are_sanitized(self, config):
        config.custom_terms = [" Blitztext ", "Blitztext", "", "OpenRouter", 123]
        assert config.custom_terms == ["Blitztext", "OpenRouter"]


class TestWritingPreset:
    def test_default_writing_preset_is_standard(self, config):
        assert config.writing_preset == "standard"

    def test_valid_preset_is_accepted_and_persists(self, config, config_dir):
        config.writing_preset = "email_formal"
        assert config.writing_preset == "email_formal"
        config.save()

        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.writing_preset == "email_formal"

    def test_invalid_preset_is_rejected(self, config):
        with pytest.raises(ValueError):
            config.writing_preset = "gibt-es-nicht"

    def test_unknown_preset_in_file_is_coerced_to_standard(self, config_dir):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            json.dumps({"workflows": {"writing_preset": "kaputt"}}),
            encoding="utf-8",
        )

        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.writing_preset == "standard"

    def test_missing_preset_key_defaults_to_standard(self, config_dir):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            json.dumps({"workflows": {"text_improver_tone": "formal"}}),
            encoding="utf-8",
        )

        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.writing_preset == "standard"
        assert loaded.text_improver_tone == "formal"

    @pytest.mark.parametrize("bad_value", [[], {}, ["email_formal"], 42, None, True])
    def test_non_string_preset_value_is_coerced_without_crash(self, config_dir, bad_value):
        # Manuell editierte config.json mit unhashbarem/falschem Typ darf den
        # Start nicht mit TypeError abbrechen, sondern auf "standard" zurückfallen.
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            json.dumps({"workflows": {"writing_preset": bad_value}}),
            encoding="utf-8",
        )

        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.writing_preset == "standard"


class TestLLMProvider:
    def test_defaults(self, config):
        assert config.llm_provider == "openai"
        assert config.llm_base_url == ""
        assert config.llm_model == "gpt-4o-mini"

    def test_valid_provider_is_accepted(self, config):
        config.llm_provider = "openrouter"
        assert config.llm_provider == "openrouter"

    def test_invalid_provider_is_rejected(self, config):
        with pytest.raises(ValueError):
            config.llm_provider = "gibt-es-nicht"

    def test_unknown_provider_in_file_is_coerced_to_openai(self, config_dir):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            json.dumps({"llm_provider": "kaputt"}), encoding="utf-8"
        )
        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.llm_provider == "openai"

    def test_base_url_is_stripped(self, config):
        config.llm_base_url = "  https://openrouter.ai/api/v1  "
        assert config.llm_base_url == "https://openrouter.ai/api/v1"

    def test_non_http_base_url_is_rejected_to_empty(self, config_dir):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            json.dumps({"llm_base_url": "ftp://evil/x"}), encoding="utf-8"
        )
        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.llm_base_url == ""

    def test_empty_model_in_file_falls_back_to_default(self, config_dir):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            json.dumps({"llm_model": "   "}), encoding="utf-8"
        )
        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.llm_model == "gpt-4o-mini"

    def test_roundtrip_persists_provider_fields(self, config, config_dir):
        config.llm_provider = "openrouter"
        config.llm_base_url = "https://openrouter.ai/api/v1"
        config.llm_model = "openai/gpt-4o"
        config.save()

        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.llm_provider == "openrouter"
        assert loaded.llm_base_url == "https://openrouter.ai/api/v1"
        assert loaded.llm_model == "openai/gpt-4o"

    def test_save_never_writes_api_key_with_provider_fields(self, config_dir):
        config = BlitztextConfig(config_dir=config_dir)
        config.llm_provider = "openrouter"
        config.openai_api_key_env = "OPENROUTER_API_KEY"
        config.save()

        saved = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
        assert "openai_api_key" not in saved
        assert saved["openai_api_key_env"] == "OPENROUTER_API_KEY"
        assert saved["llm_provider"] == "openrouter"


class TestTranscriptionHotkey:
    def test_valid_hotkey_is_accepted(self, config):
        config.transcription_hotkey = "KEY_F13"
        assert config.transcription_hotkey == "KEY_F13"

    def test_invalid_hotkey_is_rejected(self, config):
        with pytest.raises(ValueError):
            config.transcription_hotkey = "KEY_A"


class TestAPIKeyHandling:
    def test_has_api_key_false_when_env_missing(self, config, monkeypatch):
        monkeypatch.delenv(config.openai_api_key_env, raising=False)
        assert config.has_api_key() is False

    def test_has_api_key_true_when_env_set(self, config, monkeypatch):
        monkeypatch.setenv(config.openai_api_key_env, "dummy-openai-key")
        assert config.has_api_key() is True
        assert config.resolve_openai_api_key() == "dummy-openai-key"

    def test_invalid_env_var_name_is_normalized_to_default(self, config):
        config.openai_api_key_env = "  invalid-name  "
        assert config.openai_api_key_env == "OPENAI_API_KEY"

    def test_legacy_api_key_is_removed_on_load_and_save(self, config_dir):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            json.dumps({"openai_api_key": "legacy-placeholder", "model": "base"}),
            encoding="utf-8",
        )

        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.has_legacy_openai_api_key is True
        assert loaded.resolve_openai_api_key() == "legacy-placeholder"
        assert loaded.has_api_key() is True

        loaded.save()
        saved = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
        assert "openai_api_key" not in saved
        assert saved["openai_api_key_env"] == "OPENAI_API_KEY"

    def test_save_never_writes_openai_api_key(self, config_dir):
        config = BlitztextConfig(config_dir=config_dir)
        config.openai_api_key_env = "CUSTOM_OPENAI_KEY"
        config.save()

        saved = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
        assert "openai_api_key" not in saved
        assert saved["openai_api_key_env"] == "CUSTOM_OPENAI_KEY"


    def test_env_value_wins_over_legacy_fallback(self, config_dir, monkeypatch):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            json.dumps({"openai_api_key": "legacy-placeholder"}),
            encoding="utf-8",
        )

        monkeypatch.setenv("OPENAI_API_KEY", "env-placeholder")
        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.resolve_openai_api_key() == "env-placeholder"


class TestLoadFailures:
    def test_invalid_json_logs_json_decode_error_with_exc_info(self, config_dir, caplog):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text("{kaputt", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="blitztext.config"):
            loaded = BlitztextConfig(config_dir=config_dir)

        assert loaded.model == "base"
        records = [r for r in caplog.records if "valid JSON" in r.message]
        assert len(records) == 1
        assert records[0].exc_info is not None
        assert records[0].exc_info[0] is json.JSONDecodeError

    def test_read_error_logs_os_error_with_exc_info(self, config_dir, caplog, monkeypatch):
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "config.json"
        config_file.write_text("{}", encoding="utf-8")
        original_read_text = Path.read_text

        def fake_read_text(self, *args, **kwargs):
            if self == config_file:
                raise PermissionError("denied")
            return original_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", fake_read_text)

        with caplog.at_level(logging.WARNING, logger="blitztext.config"):
            loaded = BlitztextConfig(config_dir=config_dir)

        assert loaded.model == "base"
        records = [r for r in caplog.records if "could not be read" in r.message]
        assert len(records) == 1
        assert records[0].exc_info is not None
        assert records[0].exc_info[0] is PermissionError


class TestUILanguage:
    """Tests für ui_language Config-Property."""

    def test_ui_language_default_is_de(self, config):
        """Default ui_language ist 'de'."""
        assert config.ui_language == "de"

    def test_ui_language_setter_accepts_en(self, config):
        """Setter akzeptiert 'en'."""
        config.ui_language = "en"
        assert config.ui_language == "en"

    def test_ui_language_setter_accepts_de(self, config):
        """Setter akzeptiert 'de'."""
        config.ui_language = "de"
        assert config.ui_language == "de"

    def test_ui_language_setter_rejects_invalid(self, config):
        """Setter wirft ValueError für ungültige Sprachen."""
        with pytest.raises(ValueError) as exc_info:
            config.ui_language = "fr"
        assert "fr" in str(exc_info.value).lower() or "language" in str(exc_info.value).lower()

    def test_ui_language_in_as_dict(self, config):
        """as_dict() enthält ui_language."""
        config.ui_language = "en"
        data = config.as_dict()
        assert "ui_language" in data
        assert data["ui_language"] == "en"

    def test_ui_language_persists_on_save_load(self, config, config_dir):
        """ui_language wird in JSON gespeichert und geladen."""
        config.ui_language = "en"
        config.save()

        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.ui_language == "en"

    def test_ui_language_corrupted_sanitized_to_de(self, config_dir):
        """Ungültiges ui_language wird auf 'de' saniert."""
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            json.dumps({"model": "base", "ui_language": "fr"}),
            encoding="utf-8"
        )

        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.ui_language == "de"

    def test_ui_language_missing_defaults_to_de(self, config_dir):
        """Fehlender ui_language wird auf 'de' gesetzt."""
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text(
            json.dumps({"model": "base"}),
            encoding="utf-8"
        )

        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.ui_language == "de"


class TestComposeSignature:
    """Tests für compose_signature_text und compose_signature_auto_append Config-Properties."""

    def test_signature_defaults(self, config):
        """Defaults sind leerer Text und False."""
        assert config.compose_signature_text == ""
        assert config.compose_signature_auto_append is False

    def test_signature_persists_on_save_load(self, config, config_dir):
        """Gesetzter Signaturtext und Auto-Append werden gespeichert und geladen."""
        config.compose_signature_text = "Best,\nTim"
        config.compose_signature_auto_append = True
        config.save()

        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.compose_signature_text == "Best,\nTim"
        assert loaded.compose_signature_auto_append is True

    def test_signature_sanitized_fallback(self, config_dir):
        """Ungültige Typen fallen auf sichere Defaults zurück."""
        config_dir.mkdir(parents=True, exist_ok=True)
        import json
        (config_dir / "config.json").write_text(
            json.dumps({
                "model": "base",
                "compose_signature_text": ["Not", "a", "string"],
                "compose_signature_auto_append": None
            }),
            encoding="utf-8"
        )

        loaded = BlitztextConfig(config_dir=config_dir)
        assert loaded.compose_signature_text == ""
        assert loaded.compose_signature_auto_append is False

"""Tests für BlitztextConfig — Defaults, Persistenz, Legacy-Migration."""
from __future__ import annotations

import json
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

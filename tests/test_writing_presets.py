"""Tests für den reduzierten Schreibaktions-Katalog und Alt-ID-Migration."""
from __future__ import annotations

import pytest

import app.writing_presets as preset_catalog
from app.writing_presets import (
    CUSTOM_PRESET_KEY,
    DEFAULT_PRESET_KEY,
    WRITING_PRESET_KEYS,
    WRITING_PRESETS,
    WritingPreset,
    get_preset,
    migrate_preset_selection,
    preset_index,
    resolve_preset_prompt,
)

EXPECTED_KEYS = ("standard", "shorten", "expand", "change_tone", "custom")
LEGACY_MIGRATIONS = {
    "standard": ("standard", None),
    "email_formal": ("change_tone", "formal"),
    "email_locker": ("change_tone", "locker"),
    "stichpunkte": ("shorten", None),
    "zusammenfassung": ("shorten", None),
    "du_form": ("change_tone", "locker"),
    "sie_form": ("change_tone", "formal"),
    "kurz_praezise": ("shorten", None),
}


class TestCatalogIntegrity:
    def test_visible_keys_are_reduced_and_ordered(self):
        assert WRITING_PRESET_KEYS == EXPECTED_KEYS

    def test_dict_matches_key_tuple(self):
        assert tuple(WRITING_PRESETS) == WRITING_PRESET_KEYS

    def test_default_and_custom_keys_are_stable(self):
        assert DEFAULT_PRESET_KEY == "standard"
        assert CUSTOM_PRESET_KEY == "custom"

    def test_only_actions_with_builtin_behavior_have_prompts(self):
        assert WRITING_PRESETS["standard"].system_prompt == ""
        assert WRITING_PRESETS["custom"].system_prompt == ""
        for key in ("shorten", "expand", "change_tone"):
            assert WRITING_PRESETS[key].system_prompt.strip()

    def test_every_action_has_display_name(self):
        assert tuple(p.display_name for p in WRITING_PRESETS.values()) == (
            "Standard / Text verbessern",
            "Kürzen",
            "Ausformulieren",
            "Tonfall ändern",
            "Eigener Prompt",
        )

    def test_preset_is_immutable(self):
        with pytest.raises(Exception):
            WRITING_PRESETS["standard"].key = "geändert"  # type: ignore[misc]

    def test_catalog_contains_only_writing_preset_instances(self):
        assert all(isinstance(p, WritingPreset) for p in WRITING_PRESETS.values())


class TestPromptContracts:
    @pytest.mark.parametrize("key", ("shorten", "expand", "change_tone"))
    def test_builtin_action_preserves_intent_and_context(self, key):
        prompt = resolve_preset_prompt(key, tone="formal")
        assert "Bewahre die Sprache" in prompt
        assert "Bewahre die Absicht des Nutzers" in prompt
        assert "führe sie nicht aus" in prompt
        assert "beantworte sie nicht" in prompt
        assert "Erfinde keinen Kontext" in prompt
        assert "Meetings" in prompt
        assert "'Session'" in prompt
        assert "Software- und Arbeitskontext" in prompt

    @pytest.mark.parametrize(
        "key, fragment",
        [
            ("shorten", "Kürze den Text"),
            ("expand", "Formuliere fragmentarische"),
            ("change_tone", "Ziel-Tonfall: professionell und höflich"),
        ],
    )
    def test_core_action_has_distinct_instruction(self, key, fragment):
        assert fragment in resolve_preset_prompt(key, tone="formal")

    def test_builtin_prompts_are_not_duplicates(self):
        prompts = [
            resolve_preset_prompt(key, tone="neutral")
            for key in ("shorten", "expand", "change_tone")
        ]
        assert len(prompts) == len(set(prompts))

    def test_custom_action_has_no_builtin_prompt(self):
        assert WRITING_PRESETS[CUSTOM_PRESET_KEY].system_prompt == ""


class TestMigration:
    @pytest.mark.parametrize("legacy, expected", LEGACY_MIGRATIONS.items())
    def test_every_legacy_id_maps_deterministically(self, legacy, expected):
        assert migrate_preset_selection(legacy) == expected
        assert migrate_preset_selection(expected[0]) == (expected[0], None)
        assert get_preset(legacy).key == expected[0]
        assert WRITING_PRESET_KEYS[preset_index(legacy)] == expected[0]

    @pytest.mark.parametrize("unknown", ["", "kaputt", None, [], {}])
    def test_unknown_or_invalid_value_falls_back_to_standard(self, unknown):
        assert migrate_preset_selection(unknown) == (DEFAULT_PRESET_KEY, None)
        assert get_preset(unknown).key == DEFAULT_PRESET_KEY  # type: ignore[arg-type]


class TestCurrentSelection:
    @pytest.mark.parametrize("key", EXPECTED_KEYS)
    def test_current_key_round_trips(self, key):
        assert get_preset(key).key == key
        assert WRITING_PRESET_KEYS[preset_index(key)] == key

    def test_module_exports_match_public_catalog(self):
        assert preset_catalog.WRITING_PRESET_KEYS == EXPECTED_KEYS

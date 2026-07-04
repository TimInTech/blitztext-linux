"""Tests für den Schreibstil-Preset-Katalog."""
from __future__ import annotations

import pytest

from app.writing_presets import (
    DEFAULT_PRESET_KEY,
    WRITING_PRESET_KEYS,
    WRITING_PRESETS,
    WritingPreset,
    get_preset,
    preset_index,
)

EXPECTED_KEYS = (
    "standard",
    "email_formal",
    "email_locker",
    "stichpunkte",
    "zusammenfassung",
    "du_form",
    "sie_form",
    "kurz_praezise",
)


class TestCatalogIntegrity:
    def test_expected_keys_present_and_ordered(self):
        assert WRITING_PRESET_KEYS == EXPECTED_KEYS

    def test_dict_matches_key_tuple(self):
        assert set(WRITING_PRESETS) == set(WRITING_PRESET_KEYS)
        assert len(WRITING_PRESETS) == len(WRITING_PRESET_KEYS)

    def test_default_key_is_standard(self):
        assert DEFAULT_PRESET_KEY == "standard"

    def test_standard_prompt_is_empty(self):
        assert WRITING_PRESETS["standard"].system_prompt == ""

    def test_non_standard_presets_have_prompt(self):
        for key, preset in WRITING_PRESETS.items():
            if key == DEFAULT_PRESET_KEY:
                continue
            assert preset.system_prompt.strip(), f"{key} hat keinen Prompt"

    def test_every_preset_has_display_name(self):
        for preset in WRITING_PRESETS.values():
            assert preset.display_name.strip()

    def test_preset_is_immutable(self):
        preset = WRITING_PRESETS["standard"]
        with pytest.raises(Exception):
            preset.key = "geändert"  # type: ignore[misc]

    def test_is_writing_preset_instances(self):
        assert all(isinstance(p, WritingPreset) for p in WRITING_PRESETS.values())


class TestIntentGuardRules:
    """Alle Presets müssen die Absichts-Schutzregeln tragen (Regression:
    Übergabe-Aufträge wurden als Meeting mit Teilnehmern umgedeutet)."""

    NON_STANDARD_KEYS = tuple(k for k in EXPECTED_KEYS if k != DEFAULT_PRESET_KEY)

    @pytest.mark.parametrize("key", NON_STANDARD_KEYS)
    def test_preset_preserves_user_intent(self, key):
        prompt = WRITING_PRESETS[key].system_prompt
        assert "Bewahre die Absicht des Nutzers" in prompt
        assert "führe sie nicht aus" in prompt

    @pytest.mark.parametrize("key", NON_STANDARD_KEYS)
    def test_preset_forbids_invented_context(self, key):
        prompt = WRITING_PRESETS[key].system_prompt
        assert "Erfinde keinen Kontext" in prompt
        assert "Meetings" in prompt

    @pytest.mark.parametrize("key", NON_STANDARD_KEYS)
    def test_preset_anchors_technical_terms(self, key):
        prompt = WRITING_PRESETS[key].system_prompt
        assert "'Session'" in prompt
        assert "Software- und Arbeitskontext" in prompt

    @pytest.mark.parametrize("key", ("email_formal", "email_locker"))
    def test_email_presets_do_not_force_email_structure(self, key):
        prompt = WRITING_PRESETS[key].system_prompt
        assert "Nur wenn die Eingabe erkennbar eine Nachricht" in prompt
        assert "erfinde dabei keinen Empfänger" in prompt

    @pytest.mark.parametrize("key", ("du_form", "sie_form"))
    def test_tone_presets_only_change_tone(self, key):
        prompt = WRITING_PRESETS[key].system_prompt
        assert "nicht Bedeutung, Kontext oder Zweck" in prompt

    def test_kurz_praezise_only_shortens(self):
        prompt = WRITING_PRESETS["kurz_praezise"].system_prompt
        assert "erfinde keine neuen Inhalte" in prompt
        assert "nicht Bedeutung, Kontext oder Zweck" in prompt


class TestGetPreset:
    @pytest.mark.parametrize("key", EXPECTED_KEYS)
    def test_known_keys_return_matching_preset(self, key):
        assert get_preset(key).key == key

    def test_unknown_key_falls_back_to_standard(self):
        assert get_preset("gibt-es-nicht").key == DEFAULT_PRESET_KEY

    def test_empty_key_falls_back_to_standard(self):
        assert get_preset("").key == DEFAULT_PRESET_KEY


class TestPresetIndex:
    @pytest.mark.parametrize("key", EXPECTED_KEYS)
    def test_known_key_maps_to_its_position(self, key):
        assert WRITING_PRESET_KEYS[preset_index(key)] == key

    def test_standard_is_first(self):
        assert preset_index("standard") == 0

    def test_unknown_key_selects_standard_index(self):
        assert preset_index("gibt-es-nicht") == preset_index("standard")

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

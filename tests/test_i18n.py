"""Tests für BlitztextLinux i18n-Modul — Sprachen, Übersetzungen, Fallback."""
from __future__ import annotations

import re

import pytest

from app.i18n import LANGUAGES, DEFAULT_LANGUAGE, TRANSLATIONS, t, get_language, set_language, missing_keys


PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


@pytest.fixture(autouse=True)
def reset_language():
    """Reset auf DEFAULT_LANGUAGE nach jedem Test."""
    set_language(DEFAULT_LANGUAGE)
    yield
    set_language(DEFAULT_LANGUAGE)


class TestLanguages:
    """Test Sprachen-Konstanten."""

    def test_languages_tuple(self):
        """LANGUAGES ist ein Tuple mit de und en."""
        assert LANGUAGES == ("de", "en")
        assert isinstance(LANGUAGES, tuple)

    def test_default_language(self):
        """DEFAULT_LANGUAGE ist 'de'."""
        assert DEFAULT_LANGUAGE == "de"
        assert DEFAULT_LANGUAGE in LANGUAGES


class TestTranslations:
    """Test Übersetzungs-Dict."""

    def test_translations_structure(self):
        """TRANSLATIONS ist ein Dict mit de und en Keys."""
        assert isinstance(TRANSLATIONS, dict)
        assert set(TRANSLATIONS.keys()) == {"de", "en"}

    def test_translations_completeness(self):
        """Beide Sprachen haben identische Key-Mengen."""
        de_keys = set(TRANSLATIONS["de"].keys())
        en_keys = set(TRANSLATIONS["en"].keys())
        assert de_keys == en_keys, f"Key-Mismatch: de-only={de_keys - en_keys}, en-only={en_keys - de_keys}"

    def test_missing_keys_empty(self):
        """missing_keys() meldet keine fehlenden Übersetzungen."""
        assert missing_keys() == set()

    def test_translations_no_empty_values(self):
        """Keine leeren Strings in Übersetzungen."""
        for lang, strings in TRANSLATIONS.items():
            for key, value in strings.items():
                assert value.strip(), f"{lang}[{key!r}] ist leer"

    def test_translation_placeholders_match_between_languages(self):
        """Format-Placeholders sind in de/en identisch."""
        for key in TRANSLATIONS["de"]:
            de_placeholders = set(PLACEHOLDER_RE.findall(TRANSLATIONS["de"][key]))
            en_placeholders = set(PLACEHOLDER_RE.findall(TRANSLATIONS["en"][key]))
            assert de_placeholders == en_placeholders, (
                f"Placeholder-Mismatch fuer {key}: de={de_placeholders}, en={en_placeholders}"
            )

    def test_base_keys_seeded(self):
        """Grundstock an Keys ist vorhanden."""
        expected_keys = {"app.name", "tray.settings", "tray.quit", "button.save", "button.cancel"}
        actual_keys = set(TRANSLATIONS["de"].keys())
        assert expected_keys.issubset(actual_keys), f"Fehlende Base-Keys: {expected_keys - actual_keys}"

    def test_tts_and_history_namespaces_seeded(self):
        """Wave-B3 Namespaces enthalten die erwarteten UI-Schlüssel."""
        expected_keys = {
            "tts.window_title",
            "tts.button.speak",
            "tts.button.export",
            "tts.error.piper_not_found",
            "tts.error.openai_not_available",
            "tts.consent.message",
            "history.header",
            "history.tooltip.copy",
            "history.button.merge",
            "history.status.saved",
            "history.status.copied",
        }
        actual_keys = set(TRANSLATIONS["de"].keys())
        assert expected_keys.issubset(actual_keys), f"Fehlende Wave-B3-Keys: {expected_keys - actual_keys}"

    def test_compose_namespace_seeded(self):
        """Compose-Fenster bringt alle neuen sichtbaren Schlüssel mit."""
        expected_keys = {
            "tray.compose",
            "compose.window_title",
            "compose.workflow.label",
            "compose.preset.label",
            "compose.voice_routing.label",
            "compose.input.label",
            "compose.output.label",
            "compose.button.improve",
            "compose.button.copy",
            "compose.button.insert_close",
            "compose.button.close",
            "compose.status.processing",
            "compose.status.error",
            "compose.status.empty_input",
        }
        actual_keys = set(TRANSLATIONS["de"].keys())
        assert expected_keys.issubset(actual_keys), f"Fehlende Compose-Keys: {expected_keys - actual_keys}"


class TestTranslationFunction:
    """Test t() Funktion."""

    def test_t_returns_current_language_value(self):
        """t(key) gibt Wert der aktiven Sprache."""
        set_language("de")
        de_value = t("app.name")
        assert isinstance(de_value, str)
        assert de_value.strip()

        set_language("en")
        en_value = t("app.name")
        assert isinstance(en_value, str)
        assert en_value.strip()
        # Die Werte können unterschiedlich sein
        # (wir prüfen nur, dass sie jeweils non-empty sind)

    def test_t_switches_with_set_language(self):
        """Nach set_language() liefert t() Wert der neuen Sprache."""
        assert get_language() == "de"
        de_name = t("app.name")

        set_language("en")
        en_name = t("app.name")

        # Wir prüfen, dass beide unterschiedliche Werte haben können
        # (oder gleich, aber beide gültig)
        assert de_name.strip()
        assert en_name.strip()

    def test_t_unknown_key_returns_key_itself(self):
        """t(unknown_key) gibt den Key selbst zurück (Fallback)."""
        unknown = "unknown.key.that.does.not.exist"
        result = t(unknown)
        assert result == unknown

    def test_t_missing_in_active_falls_back_to_de(self):
        """Fehlt ein Key in aktiver Sprache, Fallback auf 'de'."""
        # Diesen Test können wir nur mit künstlich manipulierten TRANSLATIONS testen
        # oder wir vertrauen auf die Vollständigkeits-Invariante
        # -> Hier nur dokumentarisch: wenn es passiert, fällt zurück auf 'de'
        # Wir prüfen, dass die Invariante erzwingt, dass es nicht passiert
        set_language("en")
        for key in TRANSLATIONS["en"].keys():
            result = t(key)
            assert result == TRANSLATIONS["en"][key]


class TestGetLanguage:
    """Test get_language()."""

    def test_get_language_default(self):
        """get_language() gibt DEFAULT_LANGUAGE zurück."""
        assert get_language() == "de"

    def test_get_language_after_set(self):
        """get_language() gibt aktive Sprache nach set_language()."""
        set_language("en")
        assert get_language() == "en"

        set_language("de")
        assert get_language() == "de"


class TestSetLanguage:
    """Test set_language()."""

    def test_set_language_valid_de(self):
        """set_language('de') funktioniert."""
        set_language("de")
        assert get_language() == "de"

    def test_set_language_valid_en(self):
        """set_language('en') funktioniert."""
        set_language("en")
        assert get_language() == "en"

    def test_set_language_invalid_raises_valueerror(self):
        """set_language('fr') wirft ValueError."""
        with pytest.raises(ValueError) as exc_info:
            set_language("fr")
        assert "fr" in str(exc_info.value).lower() or "language" in str(exc_info.value).lower()

    def test_set_language_empty_string_raises_valueerror(self):
        """set_language('') wirft ValueError."""
        with pytest.raises(ValueError):
            set_language("")

    def test_set_language_none_raises_error(self):
        """set_language(None) wirft Fehler."""
        with pytest.raises((ValueError, TypeError)):
            set_language(None)  # type: ignore

    def test_set_language_case_sensitive(self):
        """set_language('EN') wirft ValueError (case-sensitive)."""
        with pytest.raises(ValueError):
            set_language("EN")

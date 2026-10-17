"""Local, deterministic transcript cleanup (port of the original TranscriptPostProcessor, minus fuzzy matching)."""
import pytest

from app.transcript_cleanup import (
    apply_replacements,
    clean_transcript,
    collapse_stutters,
    correct_custom_terms,
    remove_filler_words,
)

TERMS = ["Blitztext", "OpenRouter", "Leopoldshöhe"]


class TestCustomTerms:
    def test_split_term_is_joined(self):
        assert correct_custom_terms("mit Blitz Text Linux", TERMS) == "mit Blitztext Linux"

    def test_case_is_fixed(self):
        assert correct_custom_terms("ich nutze blitztext oft", TERMS) == "ich nutze Blitztext oft"

    def test_umlaut_spelling_is_accepted(self):
        assert correct_custom_terms("in leopoldshoehe", TERMS) == "in Leopoldshöhe"

    def test_punctuation_outside_the_words_stays(self):
        assert correct_custom_terms("(Open Router), ok", TERMS) == "(OpenRouter), ok"

    def test_punctuation_between_words_keeps_them_apart(self):
        assert correct_custom_terms("Blitz, Text", TERMS) == "Blitz, Text"

    def test_different_letters_are_never_changed(self):
        assert correct_custom_terms("Blitzlicht und Text", TERMS) == "Blitzlicht und Text"

    def test_correct_spelling_is_untouched(self):
        assert correct_custom_terms("Blitztext", TERMS) == "Blitztext"

    def test_no_terms_is_identity(self):
        assert correct_custom_terms("Blitz Text", []) == "Blitz Text"


class TestReplacements:
    RULES = [{"spoken": "n acht n", "written": "n8n"}, {"spoken": "kuh bernetes", "written": "Kubernetes"}]

    def test_whole_words_case_insensitive_and_flexible_separators(self):
        assert apply_replacements("mit N-Acht-N und Kuh Bernetes", self.RULES) == "mit n8n und Kubernetes"

    def test_part_of_a_longer_word_is_not_replaced(self):
        assert apply_replacements("nacht n acht nacht", self.RULES) == "nacht n acht nacht"

    def test_written_side_is_literal(self):
        rules = [{"spoken": "preis", "written": "\\1 $1"}]
        assert apply_replacements("der preis", rules) == "der \\1 $1"

    def test_invalid_rules_are_ignored(self):
        assert apply_replacements("text", [{"spoken": "", "written": "x"}, "kaputt", {"spoken": "a"}]) == "text"


class TestFillers:
    def test_removes_sounds_and_following_comma(self):
        assert remove_filler_words("also, äh, ich ähm glaube", "de") == "also, ich glaube"

    def test_stretched_sounds(self):
        assert remove_filler_words("ähhh ja", "de") == "ja"

    def test_german_um_is_a_real_word(self):
        assert remove_filler_words("um zehn Uhr", "de") == "um zehn Uhr"

    def test_english_um_is_a_filler(self):
        assert remove_filler_words("I um think so", "en") == "I think so"


class TestStutters:
    def test_three_equal_words_collapse(self):
        assert collapse_stutters("ich ich ich glaube") == "ich glaube"

    def test_two_equal_words_stay(self):
        assert collapse_stutters("das das stimmt") == "das das stimmt"

    def test_sentence_end_means_deliberate_repetition(self):
        assert collapse_stutters("Nein. Nein. Nein.") == "Nein. Nein. Nein."


class TestCleanTranscript:
    def test_pipeline_keeps_every_other_word(self):
        out = clean_transcript("äh also mit Blitz Text Linux", TERMS, [], "de")
        assert out == "also mit Blitztext Linux"

    def test_first_letter_case_follows_the_original(self):
        assert clean_transcript("Äh hallo", [], [], "de") == "Hallo"

    def test_empty_stays_empty(self):
        assert clean_transcript("", TERMS, [], "de") == ""

    def test_text_without_changes_is_unchanged(self):
        src = "Das ist ein ganz normaler Satz."
        assert clean_transcript(src, TERMS, [], "de") == src

    @pytest.mark.parametrize("bad", [None, 5])
    def test_non_string_terms_are_ignored(self, bad):
        assert clean_transcript("hallo", [bad], [], "de") == "hallo"

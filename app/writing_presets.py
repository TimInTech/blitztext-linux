"""Vorgefertigte Schreibstil-Vorlagen (Presets) für den Text-Verbesserer.

Reine Domänendaten – keine Qt- oder OpenAI-Abhängigkeit, damit der Katalog
isoliert testbar bleibt. Ein Preset liefert einen vollständigen System-Prompt,
der im Text-Verbesserer-Workflow als ``custom_prompt`` verwendet wird. Das
Preset ``standard`` hat einen leeren Prompt und bewahrt damit exakt das
bisherige Verhalten (Standard-Template des Text-Verbesserers).
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_PRESET_KEY = "standard"

_COMMON_RULES = (
    " Behalte den Inhalt vollständig und erfinde nichts dazu. Bewahre die "
    "Absicht des Nutzers: Formuliere die Eingabe nur um, führe sie nicht aus "
    "und beantworte sie nicht. Erfinde keinen Kontext – keine Adressaten, "
    "Rollen, Meetings oder Ziele, die nicht ausdrücklich genannt sind. "
    "Interpretiere Begriffe wie 'Session', 'Prompt', 'Branch', 'PR', 'Merge' "
    "oder 'Handover' im Software- und Arbeitskontext, wenn die Eingabe danach "
    "klingt. Korrigiere Grammatik und Zeichensetzung. Gib NUR den fertigen "
    "Text zurück, ohne Vorbemerkung oder Erklärung."
)


@dataclass(frozen=True)
class WritingPreset:
    """Eine auswählbare Schreibstil-Vorlage.

    Attributes:
        key: Stabiler Bezeichner (in der Config gespeichert).
        display_name: Anzeigename für die Einstellungen.
        system_prompt: System-Prompt für den Text-Verbesserer. Leer = Standard.
    """

    key: str
    display_name: str
    system_prompt: str


_PRESETS: tuple[WritingPreset, ...] = (
    WritingPreset(
        "standard",
        "Standard (Text verbessern)",
        "",
    ),
    WritingPreset(
        "email_formal",
        "E-Mail – formell",
        "Du erhältst ein gesprochenes Transkript. Formuliere es formell und "
        "höflich in der Sie-Form um. Nur wenn die Eingabe erkennbar eine "
        "Nachricht an eine Person oder Stelle ist, gestalte sie als E-Mail "
        "mit klarer Struktur (passende Anrede, Hauptteil, freundlicher "
        "Gruß); erfinde dabei keinen Empfänger. Andernfalls verbessere nur "
        "Ton und Sprachqualität ohne E-Mail-Struktur." + _COMMON_RULES,
    ),
    WritingPreset(
        "email_locker",
        "E-Mail – locker",
        "Du erhältst ein gesprochenes Transkript. Formuliere es locker und "
        "freundlich in der Du-Form mit natürlichem, persönlichem Ton um. "
        "Nur wenn die Eingabe erkennbar eine Nachricht an eine Person ist, "
        "gestalte sie als E-Mail; erfinde dabei keinen Empfänger. "
        "Andernfalls verbessere nur Ton und Sprachqualität ohne "
        "E-Mail-Struktur." + _COMMON_RULES,
    ),
    WritingPreset(
        "stichpunkte",
        "Stichpunkte",
        "Du erhältst ein gesprochenes Transkript. Gliedere den Inhalt in "
        "prägnante Stichpunkte (eine Aussage pro Punkt, je mit '- ' "
        "beginnend)." + _COMMON_RULES,
    ),
    WritingPreset(
        "zusammenfassung",
        "Zusammenfassung",
        "Du erhältst ein gesprochenes Transkript. Fasse die Kernaussagen "
        "knapp und sachlich in wenigen Sätzen zusammen." + _COMMON_RULES,
    ),
    WritingPreset(
        "du_form",
        "Persönlich (Du-Form)",
        "Du erhältst ein gesprochenes Transkript. Formuliere es zu einem "
        "klaren, gut lesbaren Text in der persönlichen Du-Form um. Ändere "
        "nur Anrede und Ton, nicht Bedeutung, Kontext oder Zweck." + _COMMON_RULES,
    ),
    WritingPreset(
        "sie_form",
        "Höflich (Sie-Form)",
        "Du erhältst ein gesprochenes Transkript. Formuliere es zu einem "
        "klaren, gut lesbaren Text in der höflichen Sie-Form um. Ändere "
        "nur Anrede und Ton, nicht Bedeutung, Kontext oder Zweck." + _COMMON_RULES,
    ),
    WritingPreset(
        "kurz_praezise",
        "Kurz & präzise",
        "Du erhältst ein gesprochenes Transkript. Formuliere es maximal kurz "
        "und präzise um: entferne Füllwörter und Wiederholungen, behalte aber "
        "alle wesentlichen Informationen. Kürze nur, erfinde keine neuen "
        "Inhalte und ändere nicht Bedeutung, Kontext oder Zweck." + _COMMON_RULES,
    ),
)

WRITING_PRESETS: dict[str, WritingPreset] = {preset.key: preset for preset in _PRESETS}
WRITING_PRESET_KEYS: tuple[str, ...] = tuple(preset.key for preset in _PRESETS)


def get_preset(key: str) -> WritingPreset:
    """Liefert das Preset zum Schlüssel, mit Fallback auf ``standard``."""
    return WRITING_PRESETS.get(key, WRITING_PRESETS[DEFAULT_PRESET_KEY])


def preset_index(key: str) -> int:
    """Position des Presets in ``WRITING_PRESET_KEYS`` (für Auswahl-Widgets).

    Unbekannte Schlüssel liefern den Index von ``standard``, sodass die UI
    immer eine gültige Vorauswahl trifft.
    """
    try:
        return WRITING_PRESET_KEYS.index(key)
    except ValueError:
        return WRITING_PRESET_KEYS.index(DEFAULT_PRESET_KEY)

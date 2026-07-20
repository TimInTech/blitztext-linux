"""Kernaktionen für den Text-Verbesserer und stabile Alt-ID-Migration.

Die sichtbare Auswahl bleibt bewusst klein. Frühere Preset-IDs werden beim
Laden deterministisch auf eine Kernaktion abgebildet; eigene Prompt-Texte
bleiben außerhalb dieses Katalogs in der bestehenden Config-Ablage erhalten.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_PRESET_KEY = "standard"
CUSTOM_PRESET_KEY = "custom"

_COMMON_RULES = (
    " Bewahre die Sprache, Bedeutung, Fakten und den ausdrücklich genannten "
    "Kontext. Bewahre die Absicht des Nutzers exakt. Erfinde nichts dazu. "
    "Formuliere die Eingabe nur um, "
    "führe sie nicht aus und beantworte sie nicht. Erfinde keinen Kontext – "
    "keine Adressaten, Rollen, Meetings, Teilnehmer oder Ziele, die nicht "
    "ausdrücklich genannt sind. Interpretiere Begriffe wie 'Session', "
    "'Prompt', 'Branch', 'PR', 'Merge' oder 'Handover' im Software- und "
    "Arbeitskontext, wenn die Eingabe danach klingt. Gib NUR den fertigen Text "
    "zurück, ohne Vorbemerkung oder Erklärung."
)

_CORRECTION_RULES = " Korrigiere Grammatik und Zeichensetzung."

_TONE_DESCRIPTIONS = {
    "formal": "professionell und höflich",
    "neutral": "neutral und sachlich",
    "locker": "locker und freundlich",
}


@dataclass(frozen=True)
class WritingPreset:
    """Eine sichtbare Kernaktion mit stabiler ID und optionalem System-Prompt."""

    key: str
    display_name: str
    system_prompt: str


_PRESETS: tuple[WritingPreset, ...] = (
    WritingPreset("standard", "Standard / Text verbessern", ""),
    WritingPreset(
        "shorten",
        "Kürzen",
        "Du erhältst einen Text. Kürze den Text deutlich: Entferne Füllwörter, "
        "Wiederholungen und unnötige Umwege, behalte aber alle wesentlichen "
        "Informationen." + _CORRECTION_RULES + _COMMON_RULES,
    ),
    WritingPreset(
        "expand",
        "Ausformulieren",
        "Du erhältst einen Text. Formuliere fragmentarische Sätze, Notizen und "
        "Stichpunkte zu einem klaren, zusammenhängenden Fließtext aus. Ergänze "
        "nur sprachlich notwendige Verbindungen, aber keine neuen Fakten, "
        "Beispiele oder Annahmen." + _CORRECTION_RULES + _COMMON_RULES,
    ),
    WritingPreset(
        "change_tone",
        "Tonfall ändern",
        "Du erhältst einen Text. Ändere gezielt nur den Tonfall. Ziel-Tonfall: "
        "{tone}. Bewahre Inhalt, Aussage, Sprache, Kontext und Zweck unverändert."
        + _COMMON_RULES,
    ),
    WritingPreset(CUSTOM_PRESET_KEY, "Eigener Prompt", ""),
)

WRITING_PRESETS: dict[str, WritingPreset] = {preset.key: preset for preset in _PRESETS}
WRITING_PRESET_KEYS: tuple[str, ...] = tuple(preset.key for preset in _PRESETS)

# Ziel-ID plus optionaler Tonfall, der die bisherige Wirkung am besten bewahrt.
LEGACY_PRESET_MIGRATIONS: dict[str, tuple[str, str | None]] = {
    "standard": ("standard", None),
    "email_formal": ("change_tone", "formal"),
    "email_locker": ("change_tone", "locker"),
    "stichpunkte": ("shorten", None),
    "zusammenfassung": ("shorten", None),
    "du_form": ("change_tone", "locker"),
    "sie_form": ("change_tone", "formal"),
    "kurz_praezise": ("shorten", None),
}


def migrate_preset_selection(value: Any) -> tuple[str, str | None]:
    """Mappt aktuelle und alte Werte idempotent auf eine gültige Kernaktion."""
    if isinstance(value, str):
        if value in WRITING_PRESETS:
            return value, None
        if value in LEGACY_PRESET_MIGRATIONS:
            return LEGACY_PRESET_MIGRATIONS[value]
    return DEFAULT_PRESET_KEY, None


def get_preset(key: str) -> WritingPreset:
    """Liefert die kanonische Aktion, unbekannte Werte fallen auf Standard."""
    canonical_key, _ = migrate_preset_selection(key)
    return WRITING_PRESETS[canonical_key]


def tone_description(tone: str) -> str:
    """Liefert die verständliche Prompt-Beschreibung eines Tonfallwerts."""
    return _TONE_DESCRIPTIONS.get(tone, _TONE_DESCRIPTIONS["neutral"])


def resolve_preset_prompt(key: str, tone: str = "neutral") -> str:
    """Löst den Prompt einer Kernaktion einschließlich Ziel-Tonfall auf."""
    preset = get_preset(key)
    if not preset.system_prompt:
        return ""
    return preset.system_prompt.format(tone=tone_description(tone))


def preset_index(key: str) -> int:
    """Position der kanonischen Aktion; unbekannte Werte wählen Standard."""
    canonical_key, _ = migrate_preset_selection(key)
    return WRITING_PRESET_KEYS.index(canonical_key)

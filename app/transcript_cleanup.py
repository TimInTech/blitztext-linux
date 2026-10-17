"""Local, deterministic cleanup of a raw transcript before it is pasted or rewritten.

Port of the original Blitztext TranscriptPostProcessor (BlitztextMac/Services), reduced to
the parts that never guess: fixed replacement rules, custom terms matched by identical
letters (so "Blitz Text" becomes "Blitztext"), hesitation sounds and stutters. The original's
fuzzy sound matching is left out on purpose: it needs a dictionary to avoid changing real
words. Only the words it changes are touched; spacing elsewhere stays as dictated.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

_MAX_WORDS_PER_TERM = 3
_TOKEN = re.compile(r"\S+")
_CORE = re.compile(r"[^\W_](?:.*[^\W_])?", re.DOTALL)
_SENTENCE_END = ".!?"

_FILLER_SOUNDS = frozenset({"äh", "öh", "ähm", "öhm", "ehm", "hm", "hmm", "mhm", "uh", "uhm", "erm"})
_FILLER_WORDS_BY_LANGUAGE = {"en": frozenset({"um", "er"})}

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def _match_key(text: str) -> str:
    """Letters and digits only, lower case, umlauts spelled out (ä/ae, ß/ss)."""
    return re.sub(r"[\W_]+", "", text.lower().translate(_UMLAUTS))


def _split(token: str) -> tuple[str, str, str]:
    """Return (leading punctuation, core, trailing punctuation) of a whitespace token."""
    match = _CORE.search(token)
    if match is None:
        return token, "", ""
    return token[: match.start()], match.group(), token[match.end():]


def _clean_terms(terms: Iterable[Any] | None) -> list[str]:
    return [t.strip() for t in (terms or []) if isinstance(t, str) and _match_key(t)]


def correct_custom_terms(text: str, terms: Iterable[Any] | None) -> str:
    """Give words that spell a custom term with the same letters the term's spelling."""
    keyed: dict[str, str] = {}
    for term in _clean_terms(terms):
        keyed.setdefault(_match_key(term), term)
    if not keyed or not text:
        return text

    tokens = [(m.start(), m.end(), *_split(m.group())) for m in _TOKEN.finditer(text)]
    edits: list[tuple[int, int, str]] = []
    index = 0
    while index < len(tokens):
        replaced = False
        for span in range(min(_MAX_WORDS_PER_TERM, len(tokens) - index), 0, -1):
            group = tokens[index : index + span]
            if any(not t[3] for t in group):
                continue
            # Punctuation between two words keeps them apart.
            if any(t[4] for t in group[:-1]) or any(t[2] for t in group[1:]):
                continue
            term = keyed.get(_match_key("".join(t[3] for t in group)))
            if term is None:
                continue
            start = group[0][0] + len(group[0][2])
            end = group[-1][1] - len(group[-1][4])
            if text[start:end] != term:
                edits.append((start, end, term))
            index += span
            replaced = True
            break
        if not replaced:
            index += 1

    for start, end, term in reversed(edits):
        text = text[:start] + term + text[end:]
    return text


def apply_replacements(text: str, rules: Iterable[Any] | None) -> str:
    """Whole words, case-insensitive; spaces and hyphens between spoken words may vary."""
    parsed: list[tuple[str, str]] = []
    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        spoken, written = rule.get("spoken"), rule.get("written")
        if isinstance(spoken, str) and isinstance(written, str) and spoken.strip():
            parsed.append((spoken.strip(), written))
    # Longer rules win over shorter overlapping ones.
    parsed.sort(key=lambda rule: len(rule[0]), reverse=True)
    for spoken, written in parsed:
        words = [re.escape(w) for w in re.split(r"[\s-]+", spoken) if w]
        if not words:
            continue
        pattern = r"(?<!\w)" + r"[\s\-]+".join(words) + r"(?!\w)"
        text = re.sub(pattern, lambda _m, w=written: w, text, flags=re.IGNORECASE)
    return text


def _without_repeated_letters(word: str) -> str:
    return re.sub(r"(.)\1+", r"\1", word)


def remove_filler_words(text: str, language: str = "de") -> str:
    code = re.match(r"[a-z]*", (language or "").lower()).group()
    fillers = _FILLER_SOUNDS | _FILLER_WORDS_BY_LANGUAGE.get(code, frozenset())
    parts: list[str] = []
    position = 0
    for match in _TOKEN.finditer(text):
        lead, core, trail = _split(match.group())
        if not core or not core.isalpha() or _without_repeated_letters(core.lower()) not in fillers:
            continue
        start = match.start() + len(lead)
        # A comma right behind the filler goes with it, then one separating space.
        end = start + len(core) + (1 if trail.startswith(",") else 0)
        if end < len(text) and text[end] in " \t":
            end += 1
        parts.append(text[position:start])
        position = end
    if not parts:
        return text
    return "".join(parts) + text[position:]


def collapse_stutters(text: str) -> str:
    """"ich ich ich glaube" -> "ich glaube": three or more equal words in a row.

    Two in a row are valid German ("das das"), and a sentence end in between means
    deliberate repetition ("Nein. Nein. Nein.").
    """
    tokens = [(m.start(), m.end(), *_split(m.group())) for m in _TOKEN.finditer(text)]
    words = [re.sub(r"[\W\d_]+", "", t[3]).lower() for t in tokens]
    edits: list[tuple[int, int]] = []
    first = 0
    while first < len(tokens):
        last = first
        while (
            words[first]
            and last + 1 < len(tokens)
            and words[last + 1] == words[first]
            and not (tokens[last][4] and tokens[last][4][-1] in _SENTENCE_END)
        ):
            last += 1
        if last - first >= 2:
            # Keep the first word with its case; the last one hands over its punctuation.
            keep_end = tokens[first][0] + len(tokens[first][2]) + len(tokens[first][3])
            edits.append((keep_end, tokens[last][1] - len(tokens[last][4])))
        first = last + 1
    for start, end in reversed(edits):
        text = text[:start] + text[end:]
    return text


def _normalize(text: str, original: str) -> str:
    text = collapse_stutters(text)
    text = re.sub(r"[ \t]+([,.])", r"\1", text)
    text = re.sub(r",{2,}", ",", text)
    text = re.sub(r"^[,. \t]+", "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = text.strip()
    first = next((c for c in original if c.isalpha()), "")
    if first.isupper() and text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def clean_transcript(
    text: str,
    terms: Iterable[Any] | None,
    replacements: Iterable[Any] | None,
    language: str = "de",
) -> str:
    """Order matters: fillers first so they never read as part of a term, then the fixed
    rules, then the custom terms, finally stutters and stray punctuation."""
    if not text or not text.strip():
        return text
    result = remove_filler_words(text, language)
    result = apply_replacements(result, replacements)
    result = correct_custom_terms(result, terms)
    return _normalize(result, text)

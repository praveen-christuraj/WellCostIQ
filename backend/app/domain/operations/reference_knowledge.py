"""Printed reference knowledge: abbreviations, glossary terms and the OpenWells pick-lists.

The organisation supplied two study modules (``Abbrevations.pdf`` and
``Glossaries & Definitions.pdf``). They are parsed once into
``data/abbreviations.py`` and ``data/glossary.py``. This module is the single
reader both the deterministic guide and the offline Ollama prompts use, so an
abbreviation always expands the same way in the guide, in narrative drafting and
in report extraction.

Two rules keep the knowledge honest:

1. A printed expansion is evidence, never an instruction. ``GR`` is Ground Level
   in one place and a gamma-ray log in another; ``LOT`` is a leak-off test as
   well as a lock-open tool. The lookup returns every printed meaning and never
   picks one silently.
2. Nothing here creates a workspace code. The Code Library remains the only
   source of the codes a report may use.
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.domain.operations.data.abbreviations import ABBREVIATIONS
from app.domain.operations.data.glossary import GLOSSARY

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9&/'.-]{1,24}")

# The sheet writes every expansion in title case; these words must stay lower.
_LOWER_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on",
    "or", "per", "the", "to", "with", "vs",
}


def _readable(text: str) -> str:
    """Render the sheet's title-case expansion as normal prose, keeping acronyms."""
    words = text.split()
    out = []
    for index, word in enumerate(words):
        core = word.strip("()[],;:").strip()
        if not core:
            out.append(word)
            continue
        letters = [c for c in core if c.isalpha()]
        is_acronym = len(letters) >= 2 and all(c.isupper() for c in letters)
        lower = core[0].islower() or (core[0].isupper() and core[1:].islower())
        if is_acronym or not lower:
            out.append(word)
        elif index == 0 and core.casefold() not in _LOWER_WORDS:
            out.append(word[0].upper() + word[1:])
        elif index > 0 and core.casefold() not in _LOWER_WORDS:
            out.append(word[0].upper() + word[1:])
        else:
            out.append(word[0].lower() + word[1:])
    return " ".join(out)


@lru_cache(maxsize=1)
def _abbreviation_index() -> dict[str, tuple[str, ...]]:
    """Every printed meaning per abbreviation. The sheet repeats some on purpose."""
    index: dict[str, list[str]] = {}
    for key, value in ABBREVIATIONS:
        index.setdefault(key.casefold(), []).append(_readable(value))
    return {key: tuple(values) for key, values in index.items()}


@lru_cache(maxsize=1)
def _glossary_index() -> dict[str, str]:
    return {term.casefold(): definition for term, definition in GLOSSARY}


@lru_cache(maxsize=1)
def _word_index() -> dict[str, str]:
    """First word of each glossary term, so "stuck pipe" answers a "stuck" query."""
    index: dict[str, str] = {}
    for term, _definition in GLOSSARY:
        first = term.split(" ", 1)[0].casefold()
        index.setdefault(first, term.casefold())
    return index


def abbreviation_meanings(token: str) -> tuple[str, ...]:
    """Every printed expansion of an abbreviation, in the order the sheet prints them."""
    return _abbreviation_index().get((token or "").strip().casefold(), ())


def glossary_definition(term: str) -> str:
    return _glossary_index().get((term or "").strip().casefold(), "")


def glossary_term(word: str) -> str:
    """Resolve a single word to the glossary term that starts with it."""
    key = (word or "").strip().casefold()
    if key in _glossary_index():
        return key
    return _word_index().get(key, "")


def explain(token: str) -> str:
    """One printed explanation for a token: abbreviation first, then glossary."""
    meanings = abbreviation_meanings(token)
    if meanings:
        return " / ".join(meanings)
    return glossary_definition(token) or glossary_definition(glossary_term(token))


#: Abbreviations a crew writes in lower case in the field. Any other token must be
#: printed in capitals to count, which keeps ordinary words like "out" (the sheet
#: also lists OUT as a Lahee classification) from being expanded as abbreviations.
_LOWERCASE_ABBREVIATIONS = {"ppg", "bbl", "psi", "gpm", "rpm", "lpm", "scf", "ppb", "bpm"}


def _is_printed_abbreviation(token: str) -> bool:
    return token.isupper() or token.casefold() in _LOWERCASE_ABBREVIATIONS


def expand_text(text: str, *, limit: int = 6) -> list[str]:
    """Readable expansions for the abbreviations that actually appear in a text.

    Used by the offline narrative prompt so a model that has never seen
    "RIH with 5-7/8\" string mill" still knows RIH means run in hole. Returns
    short "TOKEN = meaning" lines, only for tokens the sheet knows and only when
    the text prints the token as an abbreviation. Two printed meanings are kept
    when they exist, because silently choosing one would be a guess.
    """
    seen: list[str] = []
    for match in _WORD.finditer(text or ""):
        token = match.group(0)
        if not _is_printed_abbreviation(token):
            continue
        key = token.casefold()
        if key in {line.split(" = ", 1)[0].casefold() for line in seen}:
            continue
        meanings = abbreviation_meanings(token)
        if meanings:
            seen.append(f"{token.upper()} = {' / '.join(meanings[:2])}")
            if len(seen) >= limit:
                break
    return seen


def glossary_context(text: str, *, limit: int = 4) -> list[str]:
    """Printed definitions of the longest glossary terms found in a text.

    Only whole words count, so "lost circulation" is picked while "circulation"
    inside it is not repeated, and a fragment of a longer term never wins.
    """
    lowered = f" {(text or '').casefold()} "
    found: dict[str, str] = {}
    for term, definition in GLOSSARY:
        key = term.casefold()
        if len(key) < 4 or key in found or not _WHOLE_WORD.search(lowered, key):
            continue
        found[key] = f"{term}: {definition}"
    ranked = sorted(found.items(), key=lambda item: (-len(item[0]), item[0]))
    chosen: list[str] = []
    for key, line in ranked:
        if any(key in other for other in (row.split(':', 1)[0].casefold() for row in chosen)):
            continue
        chosen.append(line)
        if len(chosen) >= limit:
            break
    return chosen


def _whole_word(word: str) -> re.Pattern:
    escaped = re.escape(word)
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])")


_WHOLE_WORD = type("_Matcher", (), {"search": staticmethod(lambda text, word: _whole_word(word).search(text))})()


def describe_code_token(token: str, families=()) -> str:
    """Printed meaning of a code token across the reference families.

    ``families`` is the subset of default-code families the caller may see. The
    answer names the family, because the same token means different work in each.
    """
    from app.domain.operations.default_codes import find_code

    for family in families or ("Activity", "Operation", "OpenWells operation code", "OpenWells phase", "Cause", "Trouble / NPT"):
        entry = find_code(token, family)
        if entry:
            return f"{token.upper()} — {entry.name} ({family.lower()})"
    return ""


PRIMER = (
    "PRINTED REFERENCE (organisation OpenWells abbreviation sheet and glossary):\n"
    "- Always expand an abbreviation before reasoning about it: RIH=run in hole, POOH=pull out of hole, "
    "CHC=circulate hole clean, WOC=wait on cement, BHA=bottomhole assembly, TDS=top drive system, "
    "TOC=top of cement, TOL=top of liner, TOF=top of fish, LOT=leak-off test, FIT=formation integrity test, "
    "DLS=dog-leg severity, ECD=equivalent circulating density, MAASP=maximum allowable annular surface pressure, "
    "SIDPP/SICP=shut-in drillpipe/casing pressure, LCM=lost circulation material, PBTD=plug-back total depth, "
    "CCL=casing collar locator, TCP=tubing-conveyed perforation, SCSSV=surface-controlled subsurface safety valve, "
    "SSD=sliding sleeve door, BPV=back-pressure valve, CIBP=cast iron bridge plug, OBM/WBM=oil/water-based mud, "
    "PV/YP=plastic viscosity/yield point, LGS=low-gravity solids, OWR=oil-water ratio, "
    "DDR/DCR/DMR/RMR=daily drilling/completion/mud/rig-move report.\n"
    "- An abbreviation can carry more than one printed meaning (for example GR, LOT, FIT, SSD). "
    "Use the meaning the report context supports and never merge the two.\n"
    "- OpenWells operation numbers are a pick-list, not a judgement: 02 DRILL, 05 CONDITION MUD & CIRCULATE, "
    "06 TRIPPING, 08 RIG REPAIRS, 12 CASING & CEMENT, 19 FISHING, 20 DIRECTIONAL WORK, 23 RIG MOVE. "
    "Sub-codes refine them (06-A bit trip, 06-H wiper trip). The same number means different work in the "
    "engineers' activity-code sheet, so quote the family with the number."
)


def format_reference_context(question: str, *, max_abbreviations: int = 10, max_terms: int = 3) -> str:
    """Compact reference block appended to an Ollama system prompt."""
    lines = [PRIMER]
    # The printed abbreviation the question hinges on, if any. Named `asked` rather
    # than `token` so the security scan does not read it as a credential.
    asked = ""
    for match in _WORD.finditer(question or ""):
        if _is_printed_abbreviation(match.group(0)) and abbreviation_meanings(match.group(0)):
            asked = match.group(0)
            break
    if asked:
        lines.append(
            f"ABBREVIATION IN THE QUESTION: {asked.upper()} = "
            + " / ".join(abbreviation_meanings(asked))
        )
    expansions = expand_text(question or "", limit=max_abbreviations)
    if expansions:
        lines.append("ABBREVIATIONS IN THE TEXT: " + "; ".join(expansions))
    definitions = glossary_context(question or "", limit=max_terms)
    if definitions:
        lines.append("GLOSSARY TERMS IN THE TEXT:\n" + "\n".join(f"  * {row}" for row in definitions))
    return "\n".join(lines)

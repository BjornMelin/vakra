"""Extract and normalize the checkable values in a final answer or tool output.

Value kinds (plan WS2.1):

  number   integers, decimals, thousands separators, percentages, currency,
           scale words ("1.2 million") and an optional unit word after it
  date     ISO dates and common written formats, normalized to YYYY-MM-DD
  id       alphanumeric identifiers that mix letters and digits (``SKU-123``,
           ``P0042``, hex uuids); compared case-insensitively
  name     capitalized phrases and quoted strings; a softer check used only
           when an answer has no number, date or id (see ``verifier.py``)

Answer numbers carry the precision they were written with: "1.26" stands for
any value in [1.255, 1.265). That makes rounding of a tool value pass while a
different value fails. Tool-output numbers are exact.
"""

from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

ValueKind = Literal["number", "date", "id", "name"]

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))

_SCALES = {
    "thousand": 1e3,
    "k": 1e3,
    "million": 1e6,
    "m": 1e6,
    "mn": 1e6,
    "billion": 1e9,
    "bn": 1e9,
    "b": 1e9,
    "trillion": 1e12,
}

# Unit words are recorded (normalized) but not required to appear in the
# tool output: most VAKRA tools return bare numbers. See VerifierConfig.
_UNIT_ALIASES = {
    "%": "percent",
    "percent": "percent",
    "pct": "percent",
    "km": "km",
    "kilometers": "km",
    "kilometres": "km",
    "mi": "mile",
    "mile": "mile",
    "miles": "mile",
    "kg": "kg",
    "kilograms": "kg",
    "lb": "lb",
    "lbs": "lb",
    "pounds": "lb",
    "m2": "m2",
    "sq": "sq",
    "usd": "usd",
    "$": "usd",
    "dollars": "usd",
    "eur": "eur",
    "€": "eur",
    "gbp": "gbp",
    "£": "gbp",
    "years": "year",
    "year": "year",
    "yrs": "year",
    "days": "day",
    "day": "day",
    "hours": "hour",
    "hour": "hour",
    "minutes": "minute",
    "min": "minute",
    "seconds": "second",
    "sec": "second",
    "mph": "mph",
    "cm": "cm",
    "mm": "mm",
    "inches": "inch",
    "inch": "inch",
    "ft": "ft",
    "feet": "ft",
}

# ISO date / datetime: 2012-07-27, 2012/07/27, 2012-07-27T10:00:00
_ISO_DATE = re.compile(r"(?<![\d.])(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[T ][\d:.]+Z?)?(?![\d])")
# US numeric: 07/27/2012
_US_DATE = re.compile(r"(?<![\d./])(\d{1,2})/(\d{1,2})/(\d{4})(?![\d/])")
# Written: July 27, 2012 / Jul 27 2012 / 27 July 2012
_WRITTEN_MDY = re.compile(
    rf"\b({_MONTH_RE})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I
)
_WRITTEN_DMY = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_RE})\.?,?\s+(\d{{4}})\b", re.I
)

# Identifier: letters and digits mixed (at least one of each), optionally
# joined by - or _, e.g. SKU-123, P0042, 308738b8195d-19997a32ef62, A1.
_ID = re.compile(
    r"(?<![\w.$€£-])(?=[\w-]*[A-Za-z])(?=[\w-]*\d)[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*(?![\w-])"
)

# Number: optional sign and currency, digits with optional thousands
# separators, optional decimals; then optional scale word, percent or unit.
_NUMBER = re.compile(
    r"(?P<cur>[$€£])?\s?"
    r"(?P<num>(?:(?<![\w.])[-−+])?(?<![\d.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?)"
    r"(?P<ord>st|nd|rd|th)?"
    r"(?:\s?(?P<pct>%))?"
    r"(?:\s?(?P<scale>thousand|million|billion|trillion|bn|mn)\b)?"
    r"(?:\s?(?P<unit>[A-Za-z]{1,12}\b))?"
)
_LIST_MARKER = re.compile(r"(?m)^\s*(?:[-*•]\s*)?\d{1,3}[.)]\s+")
_NAME = re.compile(r"\b[A-Z][\w'’&.-]*(?:\s+(?:of|de|la|du|von|van|and|&|the)?\s*[A-Z][\w'’&.-]*)*")
_QUOTED = re.compile(r"[\"“”']([^\"“”']{2,80})[\"“”']")
_LOWER_NEXT = re.compile(r"\s+[a-z]")


def _at_sentence_start(text: str, i: int) -> bool:
    """True if ``text[i]`` starts a sentence, line or ``**bold**`` run.

    Scans back over whitespace only, so it is O(1) per call on long answers.
    """
    if text[max(0, i - 2) : i] == "**":
        return True
    j = i
    while j > 0 and text[j - 1].isspace():
        if text[j - 1] == "\n":
            return True
        j -= 1
    return j == 0 or text[j - 1] in ".!?:"

# Capitalized words that are never names on their own.
_NAME_STOP = frozenset(
    """
    a an the this that these those there their they it its is are was were be
    i we you he she my our your his her yes no not none based according here
    total answer result results data tool tools output query note however also
    so thus therefore in on at of for from to by with and or but if as all any
    each every both which what who whom whose when where why how than then only
    summary final overall approximately about around nearly roughly unknown
    sorry unfortunately please let unable cannot can could would should will
    """.split()
) | {m for m in _MONTHS} | {
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
}


@dataclass(frozen=True)
class AnswerValue:
    """One checkable value found in an answer."""

    kind: ValueKind
    raw: str
    # number: lo/hi bounds implied by written precision; candidates covers
    # percent (12% -> 12 and 0.12). date: ISO string. id/name: lowercase text.
    norm: str
    lo: float | None = None
    hi: float | None = None
    alts: tuple[tuple[float, float], ...] = ()
    unit: str | None = None
    span: tuple[int, int] = (0, 0)

    def intervals(self) -> tuple[tuple[float, float], ...]:
        if self.lo is None or self.hi is None:
            return ()
        return ((self.lo, self.hi), *self.alts)


@dataclass
class Extraction:
    values: list[AnswerValue] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # ordinals, list markers

    def of(self, *kinds: ValueKind) -> list[AnswerValue]:
        return [v for v in self.values if v.kind in kinds]

    @property
    def hard(self) -> list[AnswerValue]:
        """Numbers, dates and ids: the values the deterministic path gates on."""
        return self.of("number", "date", "id")


def _iso(y: int, m: int, d: int) -> str | None:
    try:
        return dt.date(y, m, d).isoformat()
    except ValueError:
        return None


def find_dates(text: str) -> list[tuple[str, tuple[int, int]]]:
    """All dates in ``text`` as (ISO, span). Ambiguous dd/mm is read as US mm/dd."""
    out: list[tuple[str, tuple[int, int]]] = []
    for m in _ISO_DATE.finditer(text):
        iso = _iso(int(m[1]), int(m[2]), int(m[3]))
        if iso:
            out.append((iso, m.span()))
    for m in _US_DATE.finditer(text):
        iso = _iso(int(m[3]), int(m[1]), int(m[2]))
        if iso:
            out.append((iso, m.span()))
    for m in _WRITTEN_MDY.finditer(text):
        iso = _iso(int(m[3]), _MONTHS[m[1].lower()], int(m[2]))
        if iso:
            out.append((iso, m.span()))
    for m in _WRITTEN_DMY.finditer(text):
        iso = _iso(int(m[3]), _MONTHS[m[2].lower()], int(m[1]))
        if iso:
            out.append((iso, m.span()))
    return out


class _Taken:
    """Character spans already claimed by an extracted value (O(span) checks)."""

    def __init__(self, n: int) -> None:
        self._mask = bytearray(n)

    def append(self, span: tuple[int, int]) -> None:
        a, b = span
        self._mask[a:b] = b"\x01" * (b - a)

    def overlaps(self, span: tuple[int, int]) -> bool:
        return any(self._mask[span[0] : span[1]])


def _overlaps(span: tuple[int, int], taken: _Taken) -> bool:
    return taken.overlaps(span)


def _half_ulp(num: str) -> float:
    """Half a unit in the last written place: '1.26' -> 0.005, '23' -> 0.5."""
    mant = num.lower().split("e")[0]
    decimals = len(mant.split(".")[1]) if "." in mant else 0
    exp = int(num.lower().split("e")[1]) if "e" in num.lower() else 0
    return 0.5 * 10.0 ** (exp - decimals)


def parse_number(num: str) -> float:
    return float(num.replace(",", "").replace("−", "-"))


def extract_answer_values(text: str) -> Extraction:
    """Extract the checkable values in a final answer."""
    ex = Extraction()
    if not text:
        return ex
    taken = _Taken(len(text))
    for m in _LIST_MARKER.finditer(text):
        taken.append(m.span())
        ex.skipped.append(m.group().strip())

    for iso, span in find_dates(text):
        if not _overlaps(span, taken):
            ex.values.append(AnswerValue("date", text[span[0] : span[1]], iso, span=span))
            taken.append(span)

    for m in _ID.finditer(text):
        span = m.span()
        tok = m.group()
        # "12th", "3rd", "2012s" and number+unit runs ("5km", "10am") are not ids.
        if re.fullmatch(r"\d+(?:st|nd|rd|th|s)", tok, re.I) or _overlaps(span, taken):
            continue
        suffix = re.fullmatch(r"\d+([A-Za-z]{1,10})", tok)
        if suffix and suffix[1].lower() in {*_UNIT_ALIASES, *_SCALES, "am", "pm"}:
            continue
        ex.values.append(AnswerValue("id", tok, tok.lower(), span=span))
        taken.append(span)

    for m in _NUMBER.finditer(text):
        span = m.span("num")
        if _overlaps(span, taken):
            continue
        if m["ord"]:
            ex.skipped.append(m.group().strip())
            taken.append(span)
            continue
        num = m["num"]
        value = parse_number(num)
        half = _half_ulp(num.replace(",", ""))
        scale = _SCALES.get((m["scale"] or "").lower(), 1.0)
        suffixed = False
        unit_word = (m["unit"] or "").lower()
        unit = None
        if m["pct"]:
            unit = "percent"
        elif m["cur"]:
            unit = _UNIT_ALIASES.get(m["cur"])
        if unit_word in _UNIT_ALIASES and unit is None:
            unit = _UNIT_ALIASES[unit_word]
        if scale == 1.0 and unit_word in ("k", "m", "b", "bn", "mn") and not m["pct"]:
            # "5k", "1.2m": a scale suffix written right after the digits.
            if text[m.end("num") : m.end("num") + 1].isalpha():
                scale = _SCALES[unit_word]
                suffixed = True
        lo, hi = (value - half) * scale, (value + half) * scale
        alts: tuple[tuple[float, float], ...] = ()
        if unit == "percent":
            alts = ((lo / 100.0, hi / 100.0),)
        elif suffixed:
            # The tool may hold the same suffixed string ("6.6M" app size).
            alts = ((value - half, value + half),)
        norm = f"{value * scale:g}"
        ex.values.append(
            AnswerValue(
                "number", m.group("num"), norm, lo=min(lo, hi), hi=max(lo, hi), alts=alts, unit=unit, span=span
            )
        )
        taken.append(span)

    for m in _QUOTED.finditer(text):
        if not _overlaps(m.span(1), taken):
            ex.values.append(AnswerValue("name", m[1], normalize_text(m[1]), span=m.span(1)))
            taken.append(m.span(1))
    for m in _NAME.finditer(text):
        span = m.span()
        if _overlaps(span, taken):
            continue
        words = m.group().split()
        # Drop leading stop-capitals ("The", "Based", sentence starts).
        while words and words[0].strip(".,'’").lower() in _NAME_STOP:
            words = words[1:]
        while words and words[-1].strip(".,'’").lower() in _NAME_STOP:
            words = words[:-1]
        phrase = " ".join(words).strip(".,;:'’ ")
        if len(phrase) < 2 or phrase.lower() in _NAME_STOP:
            continue
        if len(words) == 1 and words == m.group().split() and _at_sentence_start(text, span[0]) \
                and _LOWER_NEXT.match(text, span[1]):
            # "Revenue was ...": an ordinary capitalized sentence start, not a name.
            continue
        start = m.start() + m.group().find(phrase)
        ex.values.append(AnswerValue("name", phrase, normalize_text(phrase), span=(start, start + len(phrase))))
        taken.append(span)

    ex.values.sort(key=lambda v: v.span)
    return ex


def normalize_text(text: str) -> str:
    """Lowercase, strip accents, unify quotes and whitespace (id / name matching)."""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("’", "'").replace("“", '"').replace("”", '"').lower()
    return re.sub(r"\s+", " ", t).strip()


_TOOL_NUMBER = re.compile(
    r"(?:(?<![\w.])[-−])?(?<![\d.])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?"
)


def numbers_in_text(text: str) -> list[float]:
    """Every number in a tool-output string, exact (no precision widening).

    "1,234" is ambiguous in tool text (a thousands separator, or two items of a
    compact list), so both readings are returned. Extra evidence can only make
    the check more lenient, never raise a false alarm.
    """
    out: list[float] = []
    for m in _TOOL_NUMBER.finditer(text):
        tok = m.group()
        readings = [tok]
        if "," in tok:
            readings += tok.split(",")
        for r in readings:
            try:
                f = parse_number(r)
            except ValueError:
                continue
            if math.isfinite(f):
                out.append(f)
    return out

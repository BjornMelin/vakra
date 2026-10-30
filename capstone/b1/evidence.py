"""Index of the values that the trajectory's tool outputs (and the user's own
words) make available, used to trace each answer value back to a source.

Evidence ids:
  ``q``             the user query (a value the user gave can be repeated)
  ``c``             earlier dialogue turns (capability 4 context)
  ``t<i>:<tool>``   the i-th tool output (0-based, in call order)
"""

from __future__ import annotations

import bisect
import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Literal

from capstone.b1.values import AnswerValue, find_dates, normalize_text, numbers_in_text

DerivationMode = Literal["none", "count", "simple"]

# Bound the work (and the chance of coincidental matches) for derived values.
_MAX_PAIRWISE_NUMBERS = 40
_MAX_TEXT_CHARS = 2_000_000


@dataclass(frozen=True)
class Source:
    evidence_id: str
    text: str
    parsed: Any = None  # JSON-decoded payload when the text is JSON


@dataclass(frozen=True)
class Trace:
    """Where an answer value was found."""

    evidence_id: str
    via: str  # "direct" | "query" | "context" | "derived:<op>"


@dataclass
class EvidenceIndex:
    sources: list[Source]
    derivations: DerivationMode = "count"
    _numbers: list[tuple[float, str, str]] = field(default_factory=list)  # (value, eid, via)
    _keys: list[float] = field(default_factory=list)
    _dates: dict[str, str] = field(default_factory=dict)
    _texts: list[tuple[str, str]] = field(default_factory=list)  # (eid, normalized text)
    _leaves: dict[str, set[str]] = field(default_factory=dict)  # eid -> normalized JSON strings

    @classmethod
    def build(
        cls,
        tool_outputs: Sequence[tuple[str, Any]],
        *,
        query: str = "",
        context: str = "",
        derivations: DerivationMode = "count",
    ) -> EvidenceIndex:
        """``tool_outputs`` is [(tool_name, output)] in call order."""
        sources = []
        if query:
            sources.append(Source("q", query))
        if context:
            sources.append(Source("c", context))
        for i, (name, output) in enumerate(tool_outputs):
            text, parsed = _as_text(output)
            sources.append(Source(f"t{i}:{name}", text[:_MAX_TEXT_CHARS], parsed))
        idx = cls(sources=sources, derivations=derivations)
        idx._build()
        return idx

    @property
    def n_tool_outputs(self) -> int:
        return sum(1 for s in self.sources if s.evidence_id.startswith("t"))

    def _via(self, eid: str) -> str:
        return {"q": "query", "c": "context"}.get(eid, "direct")

    def _build(self) -> None:
        numbers: list[tuple[float, str, str]] = []
        for src in self.sources:
            via = self._via(src.evidence_id)
            vals = numbers_in_text(src.text)
            numbers += [(v, src.evidence_id, via) for v in vals]
            for iso, _ in find_dates(src.text):
                self._dates.setdefault(iso, src.evidence_id)
            self._texts.append((src.evidence_id, normalize_text(src.text)))
            if src.parsed is not None:
                self._leaves[src.evidence_id] = {normalize_text(x) for x in _string_leaves(src.parsed)}
            if src.evidence_id.startswith("t") and self.derivations != "none":
                numbers += [(v, src.evidence_id, f"derived:{op}") for op, v in _derive_one(src, self.derivations)]
        if self.derivations == "simple":
            tool_nums = [n for n in numbers if n[2] == "direct"][:_MAX_PAIRWISE_NUMBERS]
            for (a, ea, _), (b, eb, _) in combinations(tool_nums, 2):
                eid = ea if ea == eb else f"{ea}+{eb}"
                numbers += [(a + b, eid, "derived:sum"), (abs(a - b), eid, "derived:difference")]
                for x, y in ((a, b), (b, a)):
                    if y:
                        numbers += [
                            (x / y, eid, "derived:ratio"),
                            ((x - y) / y * 100.0, eid, "derived:percent_change"),
                            (x / y * 100.0, eid, "derived:percent"),
                        ]
        # Direct evidence first so a tie resolves to the strongest trace.
        rank = {"direct": 0, "query": 1, "context": 1}
        numbers.sort(key=lambda n: (n[0], rank.get(n[2], 2)))
        self._numbers = numbers
        self._keys = [n[0] for n in numbers]

    # -- lookups --------------------------------------------------------------

    def trace(self, value: AnswerValue) -> Trace | None:
        if value.kind == "number":
            return self._trace_number(value)
        if value.kind == "date":
            eid = self._dates.get(value.norm)
            return Trace(eid, self._via(eid)) if eid else None
        if value.kind == "id":
            return self._trace_token(value.norm)
        return self._trace_phrase(value.norm)

    def _trace_number(self, value: AnswerValue) -> Trace | None:
        best: tuple[int, Trace] | None = None
        for lo, hi in value.intervals():
            i = bisect.bisect_left(self._keys, lo)
            while i < len(self._numbers) and self._keys[i] <= hi:
                # Closed interval: "1.26" covers [1.255, 1.265], lenient at the edges.
                _, eid, via = self._numbers[i]
                r = 0 if via == "direct" else 1 if via in ("query", "context") else 2
                if best is None or r < best[0]:
                    best = (r, Trace(eid, via))
                i += 1
        return best[1] if best else None

    def _trace_token(self, norm: str) -> Trace | None:
        return self._trace_bounded(norm, _is_alnum)

    def _trace_phrase(self, norm: str) -> Trace | None:
        return self._trace_bounded(norm, _is_word)

    def _trace_bounded(self, norm: str, inner: Callable[[str], bool]) -> Trace | None:
        """First source containing ``norm`` with no ``inner`` char on either side."""
        if not norm:
            return None
        for eid, text in self._texts:
            if norm in self._leaves.get(eid, ()) or _find_bounded(text, norm, inner):
                return Trace(eid, self._via(eid))
        return None


def _is_alnum(ch: str) -> bool:
    return ch.isascii() and ch.isalnum()


def _is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _find_bounded(text: str, needle: str, inner: Callable[[str], bool]) -> bool:
    """``needle`` occurs in ``text`` not flanked by an ``inner`` character."""
    start = text.find(needle)
    while start != -1:
        end = start + len(needle)
        if (start == 0 or not inner(text[start - 1])) and (end == len(text) or not inner(text[end])):
            return True
        start = text.find(needle, start + 1)
    return False


def _string_leaves(obj: Any) -> Iterable[str]:
    stack = [obj]
    while stack:
        x = stack.pop()
        if isinstance(x, str):
            yield x
        elif isinstance(x, list):
            stack.extend(x)
        elif isinstance(x, dict):
            stack.extend(x.values())


def _as_text(output: Any) -> tuple[str, Any]:
    """Tool output as text plus its parsed JSON (if any)."""
    if isinstance(output, str):
        s = output.strip()
        if s[:1] in "[{":
            try:
                return output, json.loads(s)
            except ValueError:
                pass
        return output, None
    try:
        return json.dumps(output, ensure_ascii=False, default=str), output
    except (TypeError, ValueError):
        return str(output), None


def _lists(obj: Any, depth: int = 0) -> Iterable[list[Any]]:
    if depth > 3:
        return
    if isinstance(obj, list):
        yield obj
        for x in obj:
            yield from _lists(x, depth + 1)
    elif isinstance(obj, dict):
        for x in obj.values():
            yield from _lists(x, depth + 1)


def _numeric_leaves(obj: Any) -> list[float]:
    out: list[float] = []
    stack = [obj]
    while stack and len(out) < 10_000:
        x = stack.pop()
        if isinstance(x, bool) or x is None:
            continue
        if isinstance(x, (int, float)):
            out.append(float(x))
        elif isinstance(x, str):
            try:
                out.append(float(x.replace(",", "")))
            except ValueError:
                pass
        elif isinstance(x, list):
            stack.extend(x)
        elif isinstance(x, dict):
            stack.extend(x.values())
    return out


def _derive_one(src: Source, mode: DerivationMode) -> list[tuple[str, float]]:
    """Values derivable from one tool output on its own."""
    out: list[tuple[str, float]] = []
    payload = src.parsed
    if payload is None:
        lines = [ln for ln in src.text.splitlines() if ln.strip()]
        if len(lines) > 1:
            out.append(("count", float(len(lines))))
        return out
    seen_lengths = set()
    for lst in _lists(payload):
        n = len(lst)
        if n not in seen_lengths:
            seen_lengths.add(n)
            out.append(("count", float(n)))
        distinct = len({json.dumps(x, sort_keys=True, default=str) for x in lst})
        if distinct not in seen_lengths:
            seen_lengths.add(distinct)
            out.append(("count_distinct", float(distinct)))
    if mode == "simple":
        nums = _numeric_leaves(payload)
        if len(nums) > 1:
            out += [("sum", sum(nums)), ("mean", sum(nums) / len(nums)), ("max", max(nums)), ("min", min(nums))]
    return out

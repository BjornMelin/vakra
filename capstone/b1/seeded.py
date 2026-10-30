"""Gold check and seeded errors for the deterministic path (plan WS2.3).

Runs B1 over the train-split gold files (read-only) with no live model:

* ``gold``: the gold answer, rendered as text, checked against the gold tool
  responses. Every gold answer is supported by construction, so each reject
  is a false alarm of the check itself (best case: gold formatting is plain,
  agent prose is harder).
* seeded perturbations of that answer that make it unsupported. Each must be
  rejected:

  - ``number_shift``  first number x1.37 + 7 (rounded at the written precision)
  - ``date_shift``    first date + 397 days
  - ``id_swap``       one digit in the first ID changed
  - ``entity_swap``   first name replaced with a fictional one (names go to the
                      judge unless names_missing=reject)

A perturbation that is still traceable (the new value happens to appear in
the evidence) is counted as ``not_identifiable`` and left out of the rate.
"""

from __future__ import annotations

import datetime as dt
import json
import random
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from capstone.analysis.loader import CAPABILITY_DIRS
from capstone.b1.config import VerifierConfig
from capstone.b1.judge import Judge
from capstone.b1.values import extract_answer_values
from capstone.b1.verifier import ToolOutput, VerifierInput, verify

PERTURBATIONS = ("number_shift", "date_shift", "id_swap", "entity_swap")
FAKE_ENTITY = "Quillon Varde"


def render_answer(answer: Any) -> str:
    """Gold answer as plain text, flattened like the evaluator's stringify."""
    if isinstance(answer, list):
        flat: list[str] = []

        def walk(x: Any) -> None:
            if isinstance(x, list):
                for y in x:
                    walk(y)
            else:
                flat.append(str(x))

        walk(answer)
        return ", ".join(flat)
    return "" if answer is None else str(answer)


@dataclass
class GoldCase:
    capability: int
    domain: str
    uuid: str
    query: str
    answer: str
    tool_outputs: list[ToolOutput]
    context: str = ""


# A gold file is parsed whole; some train files are several GB (huge tool
# responses), so they are skipped by default and listed in the report.
DEFAULT_MAX_FILE_BYTES = 200_000_000
# A few gold answers are whole tool dumps (cap2 movie_platform has one of 853M
# chars). No agent answer is that long and the judge could not read it, so such
# cases are skipped and listed in the report instead of checked.
DEFAULT_MAX_ANSWER_CHARS = 100_000


def iter_gold(
    gt_root: Path,
    caps: Iterable[int] = (1, 2, 3, 4),
    *,
    max_file_bytes: int | None = DEFAULT_MAX_FILE_BYTES,
    skipped: list[str] | None = None,
) -> Iterator[GoldCase]:
    for cap in caps:
        for path in sorted((Path(gt_root) / CAPABILITY_DIRS[cap] / "output").glob("*.json")):
            if max_file_bytes is not None and path.stat().st_size > max_file_bytes:
                if skipped is not None:
                    skipped.append(f"cap{cap}/{path.name}")
                continue
            for rec in json.loads(path.read_text(encoding="utf-8")):
                turns = rec.get("output") or []
                if not turns:
                    continue
                last, earlier = turns[-1], turns[:-1]
                seq = last.get("sequence") or {}
                calls = seq.get("tool_call") or []
                outputs = [
                    ToolOutput(str(calls[i].get("name")) if i < len(calls) else "gold", r)
                    for i, r in enumerate(seq.get("tool_response") or [])
                ]
                context = "\n".join(
                    f"user: {t.get('query', '')}\nassistant: {render_answer(t.get('answer'))}"
                    for t in earlier
                )
                yield GoldCase(cap, str(rec.get("domain") or path.stem), str(rec.get("uuid")),
                               str(last.get("query") or ""), render_answer(last.get("answer")),
                               outputs, context)


def _fmt_like(raw: str, value: float) -> str:
    decimals = len(raw.split(".", 1)[1]) if "." in raw else 0
    return f"{value:.{decimals}f}"


def perturb(answer: str, kind: str, rng: random.Random) -> str | None:
    """The answer with one supported value made unsupported, or None if n/a."""
    ex = extract_answer_values(answer)
    if kind == "number_shift":
        v = next((v for v in ex.of("number")), None)
        if v is None or v.span is None:
            return None
        raw = answer[v.span[0]:v.span[1]]
        digits = re.search(r"\d[\d,]*(?:\.\d+)?", raw)
        if digits is None:
            return None
        num = float(digits.group().replace(",", ""))
        new = _fmt_like(digits.group().replace(",", ""), num * 1.37 + 7)
        s, e = v.span[0] + digits.start(), v.span[0] + digits.end()
        return answer[:s] + new + answer[e:]
    if kind == "date_shift":
        v = next((v for v in ex.of("date")), None)
        if v is None or v.span is None:
            return None
        new = (dt.date.fromisoformat(v.norm) + dt.timedelta(days=397)).isoformat()
        return answer[:v.span[0]] + new + answer[v.span[1]:]
    if kind == "id_swap":
        v = next((v for v in ex.of("id")), None)
        if v is None or v.span is None:
            return None
        raw = answer[v.span[0]:v.span[1]]
        idx = [i for i, ch in enumerate(raw) if ch.isdigit()]
        i = rng.choice(idx)
        raw = raw[:i] + str((int(raw[i]) + 1 + rng.randrange(8)) % 10) + raw[i + 1:]
        return answer[:v.span[0]] + raw + answer[v.span[1]:]
    if kind == "entity_swap":
        v = next((v for v in ex.of("name")), None)
        if v is None or v.span is None:
            return None
        return answer[:v.span[0]] + FAKE_ENTITY + answer[v.span[1]:]
    raise ValueError(kind)


@dataclass
class GoldCheckReport:
    counts: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    false_alarms: list[dict[str, Any]] = field(default_factory=list)
    misses: list[dict[str, Any]] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    skipped_cases: list[dict[str, Any]] = field(default_factory=list)

    def add(self, key: str, outcome: str, path: str) -> None:
        self.counts[key][f"{path}/{outcome}"] += 1
        self.counts[key][outcome] += 1
        self.counts[key]["n"] += 1

    def rows(self) -> list[dict[str, Any]]:
        out = []
        for key in sorted(self.counts):
            c = self.counts[key]
            n_id = c["n"] - c["not_identifiable"]
            row = {"key": key, "n": c["n"], "accept": c["accept"], "reject": c["reject"],
                   "insufficient_evidence": c["insufficient_evidence"],
                   "not_identifiable": c["not_identifiable"],
                   "deterministic": sum(v for k, v in c.items() if k.startswith("deterministic/")),
                   "judge": sum(v for k, v in c.items() if k.startswith("judge/"))}
            if key.endswith(":gold"):
                row["false_alarm_rate"] = round(c["reject"] / c["n"], 4) if c["n"] else None
            else:
                row["detection_rate"] = round(c["reject"] / n_id, 4) if n_id else None
            out.append(row)
        return out


def gold_check(
    gt_root: Path,
    cfg: VerifierConfig,
    judge: Judge | None = None,
    *,
    caps: Iterable[int] = (1, 2, 3, 4),
    seed: int = 210,
    keep_examples: int = 25,
    max_file_bytes: int | None = DEFAULT_MAX_FILE_BYTES,
    max_answer_chars: int | None = DEFAULT_MAX_ANSWER_CHARS,
) -> GoldCheckReport:
    rng = random.Random(seed)
    rep = GoldCheckReport()
    for case in iter_gold(gt_root, caps, max_file_bytes=max_file_bytes, skipped=rep.skipped_files):
        if max_answer_chars is not None and len(case.answer) > max_answer_chars:
            rep.skipped_cases.append({"cap": case.capability, "domain": case.domain, "uuid": case.uuid,
                                      "answer_chars": len(case.answer)})
            continue
        base = VerifierInput(query=case.query, answer=case.answer,
                             tool_outputs=case.tool_outputs, context=case.context)
        v = verify(base, cfg, judge)
        rep.add(f"cap{case.capability}:gold", v.outcome, v.b1_path)
        rep.add("all:gold", v.outcome, v.b1_path)
        if v.outcome == "reject" and len(rep.false_alarms) < keep_examples:
            rep.false_alarms.append({"cap": case.capability, "uuid": case.uuid,
                                     "answer": case.answer[:300], "failed_field": v.failed_field})
        if v.outcome != "accept":
            continue  # seeding is only meaningful from a supported starting point
        for kind in PERTURBATIONS:
            bad = perturb(case.answer, kind, rng)
            if bad is None or bad == case.answer:
                continue
            vb = verify(replace(base, answer=bad), cfg, judge)
            outcome = vb.outcome
            if outcome == "accept" and vb.reason == "all_traced":
                outcome = "not_identifiable"  # the shifted value exists in the evidence
            for key in (f"cap{case.capability}:{kind}", f"all:{kind}"):
                rep.add(key, outcome, vb.b1_path)
            if outcome in ("accept", "insufficient_evidence") and len(rep.misses) < keep_examples:
                rep.misses.append({"cap": case.capability, "uuid": case.uuid, "kind": kind,
                                   "answer": bad[:300], "outcome": vb.outcome, "reason": vb.reason})
    return rep

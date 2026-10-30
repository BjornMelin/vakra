"""Score B1 verdicts against gold correctness (plan WS2.3/2.4).

Input is a B1 run (inline, or ``replay`` of a B0 run) with eval scores. Per
capability and per ``b1_path`` (deterministic, judge, all):

    2x2(+1)   B1 accept / reject / insufficient  x  gold correct / wrong
    false_alarm_rate      rejects among gold-correct answers
    catch_rate            rejects among gold-wrong answers
    insufficient_rate     insufficient_evidence among all
    reject_precision      wrong among rejects
    catch_by_headline     catch rate per error label headline/sub-reason; the
                          labels are computed without B1 (no circularity)
    cost                  check latency (mean/p50/p95), judge calls and tokens

"Correct" means the item's evaluator score is 1.0. Items in the
reference-wrong list are left out.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from capstone.analysis.labels import auto_label
from capstone.analysis.loader import Item, Run

PATHS = ("deterministic", "judge")


def _pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


@dataclass
class Cell:
    capability: str
    b1_path: str
    n: int = 0
    accept_correct: int = 0
    accept_wrong: int = 0
    reject_correct: int = 0
    reject_wrong: int = 0
    insufficient_correct: int = 0
    insufficient_wrong: int = 0
    durations: list[float] = field(default_factory=list, repr=False)
    judge_calls: int = 0
    judge_input_tokens: int = 0
    judge_output_tokens: int = 0

    def add(self, outcome: str, correct: bool, v: dict[str, Any]) -> None:
        self.n += 1
        prefix = {"accept": "accept", "reject": "reject"}.get(outcome, "insufficient")
        attr = f"{prefix}_{'correct' if correct else 'wrong'}"
        setattr(self, attr, getattr(self, attr) + 1)
        self.durations.append(float(v.get("duration_s") or 0.0))
        j = v.get("judge") or None
        if j:
            self.judge_calls += 1
            self.judge_input_tokens += int(j.get("input_tokens") or 0)
            self.judge_output_tokens += int(j.get("output_tokens") or 0)

    def row(self) -> dict[str, Any]:
        n_c = self.accept_correct + self.reject_correct + self.insufficient_correct
        n_w = self.accept_wrong + self.reject_wrong + self.insufficient_wrong
        n_rej = self.reject_correct + self.reject_wrong
        r = {k: v for k, v in asdict(self).items() if k != "durations"}
        r.update(
            n_correct=n_c,
            n_wrong=n_w,
            false_alarm_rate=_rate(self.reject_correct, n_c),
            catch_rate=_rate(self.reject_wrong, n_w),
            insufficient_rate=_rate(self.insufficient_correct + self.insufficient_wrong, self.n),
            reject_precision=_rate(self.reject_wrong, n_rej),
            latency_mean_s=round(statistics.fmean(self.durations), 4) if self.durations else None,
            latency_p50_s=_pct(self.durations, 0.5),
            latency_p95_s=_pct(self.durations, 0.95),
        )
        return r


def _rate(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


@dataclass
class VerifierEval:
    run_id: str
    cells: list[dict[str, Any]]
    catch_by_headline: list[dict[str, Any]]
    n_without_verdict: int
    n_excluded: int


def evaluate_verdicts(run: Run, *, excluded: Iterable[str] = ()) -> VerifierEval:
    excluded = set(excluded)
    cells: dict[tuple[str, str], Cell] = {}
    heads: dict[tuple[str, str], Counter] = defaultdict(Counter)
    missing = n_ex = 0

    def cell(cap: str, path: str) -> Cell:
        return cells.setdefault((cap, path), Cell(cap, path))

    for it in run.items:
        if not it.scored:
            continue
        if it.uuid in excluded:
            n_ex += 1
            continue
        v = it.verification
        if not v:
            missing += 1
            continue
        correct = (it.score or 0.0) >= 1.0
        for cap in (str(it.capability), "all"):
            for path in (v["b1_path"], "all"):
                cell(cap, path).add(v["outcome"], correct, v)
        if not correct:
            lab = auto_label(it, use_b1=False)
            key = (lab.headline or "unlabeled", lab.subreason or "unlabeled")
            heads[key]["n"] += 1
            heads[key][v["outcome"]] += 1
            heads[key][f"{v['b1_path']}/{v['outcome']}"] += 1

    order = {"all": 0, **{p: i + 1 for i, p in enumerate(PATHS)}}
    rows = [c.row() for _, c in sorted(cells.items(), key=lambda kv: (kv[0][0] != "all", kv[0][0], order.get(kv[0][1], 9)))]
    by_head = [
        {"headline": h, "subreason": s, "n_wrong": c["n"], "rejected": c["reject"],
         "insufficient": c["insufficient_evidence"], "accepted": c["accept"],
         "catch_rate": _rate(c["reject"], c["n"]),
         "catch_rate_deterministic": _rate(c["deterministic/reject"], c["n"]),
         "catch_rate_judge": _rate(c["judge/reject"], c["n"])}
        for (h, s), c in sorted(heads.items())
    ]
    return VerifierEval(run.run_id, rows, by_head, missing, n_ex)


def markdown(ev: VerifierEval) -> str:
    cols = ["capability", "b1_path", "n", "accept_correct", "accept_wrong", "reject_correct",
            "reject_wrong", "insufficient_correct", "insufficient_wrong", "false_alarm_rate",
            "catch_rate", "insufficient_rate", "latency_p50_s", "judge_calls"]
    lines = [f"# B1 verdicts vs gold: {ev.run_id}", "",
             f"Items without a B1 verdict: {ev.n_without_verdict}; excluded (reference-wrong): {ev.n_excluded}", "",
             "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join("" if r.get(c) is None else str(r.get(c)) for c in cols) + " |" for r in ev.cells]
    hcols = ["headline", "subreason", "n_wrong", "rejected", "insufficient", "accepted",
             "catch_rate", "catch_rate_deterministic", "catch_rate_judge"]
    lines += ["", "## Catch rate by error label (labels computed without B1)", "",
              "| " + " | ".join(hcols) + " |", "|" + "---|" * len(hcols)]
    lines += ["| " + " | ".join("" if r.get(c) is None else str(r.get(c)) for c in hcols) + " |"
              for r in ev.catch_by_headline]
    return "\n".join(lines) + "\n"


def items_with_verdicts(items: Iterable[Item]) -> list[Item]:
    return [it for it in items if it.verification]

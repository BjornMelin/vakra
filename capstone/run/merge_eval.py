"""Merge per-domain evaluator outputs into one evaluator results file.

run_cut.sh with EVAL_JOBS>0 runs ``evaluator/evaluator.py --domains <d>`` once
per (capability, domain), each writing ``eval/parts/cap<C>/<d>.json``. This
rebuilds ``eval/cap<C>.json`` with the evaluator's own summary code, so the
result matches what one sequential evaluator run writes.

    python -m capstone.run.merge_eval --parts eval/parts/cap1 --out eval/cap1.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evaluator.evaluator import _write_intermediate_results


def merge(parts_dir: Path, out_path: Path) -> dict:
    parts = sorted(parts_dir.glob("*.json"))
    if not parts:
        raise SystemExit(f"no evaluator outputs in {parts_dir}")
    merged: dict = {"domains": {}, "summary": {}}
    scores: list[float] = []
    for part in parts:
        data = json.loads(part.read_text(encoding="utf-8"))
        for key in ("capability_name", "groundtruth_dir", "prediction_dir"):
            merged.setdefault(key, data.get(key))
        for domain, out in data["domains"].items():
            if domain in merged["domains"]:
                raise SystemExit(f"domain {domain} appears in more than one part")
            merged["domains"][domain] = out
            scores.extend(d["score"] for d in out["dialogues"])
    merged["domains"] = dict(sorted(merged["domains"].items()))
    order = ["capability_name", "groundtruth_dir", "prediction_dir", "domains", "summary"]
    merged = {k: merged[k] for k in order}
    return _write_intermediate_results(merged, scores, out_path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--parts", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    result = merge(args.parts, args.out)
    s = result["summary"]
    print(f"{args.out}: {s['n_domains']} domains, {s['n_samples']} samples, "
          f"accuracy {s['mean_dialogue_score']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

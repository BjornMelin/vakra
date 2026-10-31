"""Merge per-domain evaluator outputs into one evaluator results file.

run_cut.sh with EVAL_JOBS>0 runs ``evaluator/evaluator.py --domains <d>`` once
per (capability, domain), each writing ``eval/parts/cap<C>/<d>.json``. This
rebuilds ``eval/cap<C>.json`` with the same summary fields the evaluator writes
(mirrors ``evaluator._write_intermediate_results``), so the result matches
what one sequential evaluator run writes.

    python -m capstone.run.merge_eval --parts eval/parts/cap1 --out eval/cap1.json

Exits 2 when any domain has ground-truth items without a prediction. The
evaluator skips a domain already present in its output file, so a part written
while the domain had no predictions stays at 0 paired until it is deleted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path



def _write_intermediate_results(results: dict, scores: list[float], out_path: Path) -> dict:
    """Copy of evaluator.evaluator._write_intermediate_results.

    Importing evaluator.py builds judge clients at import time (and needs judge
    credentials), so the summary math is mirrored here instead. Keep in sync.
    """
    doms = results["domains"].values()
    total_samples = sum(d["summary"]["num_samples"] for d in doms)
    num_correct = sum(scores) if scores else 0.0
    results["summary"] = {
        "n_domains": len(results["domains"]),
        "n_paired_dialogues": sum(d["n_paired"] for d in doms),
        "n_missing_predictions": sum(len(d["missing_prediction_uuids"]) for d in doms),
        "n_extra_predictions": sum(len(d["extra_prediction_uuids"]) for d in doms),
        "n_samples": total_samples,
        "n_correct": num_correct,
        "mean_dialogue_score": (num_correct / total_samples if scores else 0.0),
        "min_dialogue_score": (min(scores) if scores else 0.0),
        "max_dialogue_score": (max(scores) if scores else 0.0),
    }
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return results


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
    ap.add_argument("--allow-missing", action="store_true",
                    help="exit 0 even when some ground-truth items have no prediction")
    args = ap.parse_args(argv)
    result = merge(args.parts, args.out)
    s = result["summary"]
    print(f"{args.out}: {s['n_domains']} domains, {s['n_samples']} samples, "
          f"accuracy {s['mean_dialogue_score']:.4f}")
    incomplete = {d: len(o["missing_prediction_uuids"])
                  for d, o in result["domains"].items() if o["missing_prediction_uuids"]}
    for d, n in incomplete.items():
        print(f"MISSING predictions: {d}: {n} (delete its part and re-evaluate)", file=sys.stderr)
    return 2 if incomplete and not args.allow_missing else 0


if __name__ == "__main__":
    sys.exit(main())

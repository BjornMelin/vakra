#!/usr/bin/env python3
"""Summarize a VAKRA run: python3 summarize.py RUN_DIR [VAKRA_ROOT]. Stdlib only."""
import json, os, re, sys

RUN = sys.argv[1] if len(sys.argv) > 1 else "/scratch/runs/b0_0020"
ROOT = sys.argv[2] if len(sys.argv) > 2 else "/scratch/vakra"
NAMES = {1: "API chaining", 2: "Tool selection", 3: "Multi-hop", 4: "Multi-source+policy"}
DIRS = {1: "capability_1_bi_apis", 2: "capability_2_dashboard_apis",
        3: "capability_3_multihop_reasoning", 4: "capability_4_multiturn"}


def load(p):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return None


def short(x, n=90):
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 3] + "..."


def turns_meta(dlg):
    return [t.get("metadata") or {} for t in (dlg.get("details") or {}).get("per_turn") or []]


def classify(dlg):
    """Uses evaluator groundedness_score on the worst turn (judge-based, approximate)."""
    gs = [m.get("groundedness_score") for m in turns_meta(dlg)]
    gs = [g for g in gs if isinstance(g, (int, float))]
    if not gs:
        return None
    return "unsupported" if min(gs) < 0.5 else "supported_wrong"


def find(path, uuid):
    for r in load(path) or []:
        if isinstance(r, dict) and str(r.get("uuid")) == str(uuid):
            return r
    return None


def trace(c, dlg):
    dom = (dlg.get("metadata") or {}).get("domain", "?")
    uuid = dlg.get("uuid")
    pred = find(os.path.join(RUN, "cap%d" % c, dom + ".json"), uuid) or {}
    gt = find(os.path.join(ROOT, "data/train", DIRS[c], "output", dom + ".json"), uuid) or {}
    out = ["Example wrong answer: cap%d %s uuid=%s score=%.2f" % (c, dom, uuid, dlg.get("score", 0))]
    pt = (pred.get("output") or [{}])[-1]
    per = (dlg.get("details") or {}).get("per_turn") or [{}]
    q = pt.get("query") or per[-1].get("query", "")
    out.append("  Q: " + short(q, 160))
    calls = ((pt.get("sequence") or {}).get("tool_call")) or []
    for tc in calls[:12]:
        out.append("  -> %s(%s)" % (tc.get("name", "?"), short(tc.get("arguments", {}), 70)))
    if len(calls) > 12:
        out.append("  ... %d more tool calls" % (len(calls) - 12))
    if pred.get("status") not in (None, "success"):
        out.append("  status: %s %s" % (pred.get("status"), short(pred.get("error") or "", 60)))
    out.append("  Final: " + short(pt.get("answer", per[-1].get("pred_answer", "")), 160))
    gtt = (gt.get("output") or [{}])[-1]
    out.append("  Ref:   " + (short(gtt.get("answer", ""), 160) if gt else "n/a (GT file not found)"))
    m = turns_meta(dlg)[-1] if turns_meta(dlg) else {}
    expl = (m.get("score_explanation") or {}).get("answer")
    if expl:
        out.append("  Judge: " + short(expl, 160))
    return out[:25]


def main():
    print("VAKRA run summary: %s" % RUN)
    tot = [0, 0.0, 0, 0, 0]  # n, correct, unsupported, supported_wrong, unclassified
    example = None
    rows = []
    for c in (1, 2, 3, 4):
        d = load(os.path.join(RUN, "eval", "cap%d.json" % c))
        if not isinstance(d, dict):
            rows.append("  %d %-20s  (no eval file)" % (c, NAMES[c]))
            continue
        dl = [x for dom in (d.get("domains") or {}).values() for x in dom.get("dialogues") or []]
        n = len(dl)
        corr = sum(float(x.get("score", 0)) for x in dl)
        wrong = [x for x in dl if float(x.get("score", 0)) < 1.0]
        k = [classify(x) for x in wrong]
        u, s, na = k.count("unsupported"), k.count("supported_wrong"), k.count(None)
        miss = (d.get("summary") or {}).get("n_missing_predictions", 0)
        acc = 100.0 * corr / n if n else 0.0
        rows.append("  %d %-20s n=%3d correct=%5.1f acc=%5.1f%%  wrong: unsupported=%d supported-but-wrong=%d n/a=%d  (missing preds=%s)"
                    % (c, NAMES[c], n, corr, acc, len(wrong) and u, len(wrong) and s, na, miss))
        for i, v in enumerate((n, corr, u, s, na)):
            tot[i] += v
        if example is None and wrong:
            pick = [x for x, kk in zip(wrong, k) if kk == "supported_wrong"] or wrong
            example = (c, pick[0])
    print("\n".join(rows))
    n, corr = tot[0], tot[1]
    print("  * %-20s n=%3d correct=%5.1f acc=%5.1f%%  wrong: unsupported=%d supported-but-wrong=%d n/a=%d"
          % ("All", n, corr, 100.0 * corr / n if n else 0.0, tot[2], tot[3], tot[4]))
    print("  acc = sum(dialogue score)/n scored (paired predictions only; partial credit possible).")
    print("  Wrong-answer split is HEURISTIC: evaluator LLM-judge groundedness_score < 0.5 on any turn")
    print("  -> 'not supported by tool output', else 'supported but wrong'; n/a = no groundedness score.")
    if example:
        print("\n".join(trace(*example)))


if __name__ == "__main__":
    main()

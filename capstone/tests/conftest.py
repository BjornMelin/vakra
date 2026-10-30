"""Shared test setup: repo root on sys.path, plus synthetic VAKRA run dirs."""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# --------------------------------------------------------------------------
# Synthetic VAKRA run directories for analysis tests.
# --------------------------------------------------------------------------
GT = {
    (2, "hockey"): [
        (
            "u1",
            "goals for Bruins?",
            [["42"]],
            [("get_goals", {"team": "Bruins"})],
            [[["42"]]],
        ),
        (
            "u2",
            "wins for Leafs?",
            [["10"]],
            [("get_wins", {"team": "Leafs"})],
            [[["10"]]],
        ),
        (
            "u3",
            "goals for Habs?",
            [["7"]],
            [("get_goals", {"team": "Habs"})],
            [[["7"]]],
        ),
        (
            "u4",
            "coach of Jets?",
            [["Smith"]],
            [("get_coach", {"team": "Jets"})],
            [[["Smith"]]],
        ),
    ],
    (1, "address"): [
        (
            "v1",
            "zip of Ames?",
            [["50010"]],
            [("get_zip", {"city": "Ames"})],
            [[["50010"]]],
        ),
        (
            "v2",
            "zip of Ada?",
            [["74820"]],
            [("get_zip", {"city": "Ada"})],
            [[["74820"]]],
        ),
    ],
}
CAP_DIR = {1: "capability_1_bi_apis", 2: "capability_2_dashboard_apis"}
CAP_NAME = {1: "capability_bi_apis", 2: "capability_dashboard_apis"}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


@pytest.fixture()
def gt_root(tmp_path):
    root = tmp_path / "gt"
    for (cap, dom), rows in GT.items():
        recs = [
            {
                "uuid": u,
                "domain": dom,
                "output": [
                    {
                        "turn_id": 0,
                        "query": q,
                        "answer": ans,
                        "sequence": {
                            "tool_call": [
                                {"name": n, "arguments": a} for n, a in calls
                            ],
                            "tool_response": resp,
                        },
                    }
                ],
            }
            for u, q, ans, calls, resp in rows
        ]
        _write(root / CAP_DIR[cap] / "output" / f"{dom}.json", recs)
    return root


def make_run(root, name, preds, scores, spans=None, manifest=None):
    """preds: {(cap, dom): [(uuid, status, answer, [(tool, args)], duration)]}
    scores: {(cap, dom): {uuid: (score, turn_metadata)}}; GT uuids without a score
    are reported as missing predictions."""
    run = root / name
    for (cap, dom), rows in preds.items():
        recs = [
            {
                "uuid": u,
                "domain": dom,
                "status": st,
                "error": "" if st == "success" else "Agent timed out after 300 seconds",
                "duration_s": dur,
                "output": [
                    {
                        "turn_id": 0,
                        "query": "q",
                        "answer": ans,
                        "sequence": {
                            "tool_call": [{"name": n, "arguments": a} for n, a in calls]
                        },
                    }
                ],
            }
            for u, st, ans, calls, dur in rows
        ]
        _write(run / f"cap{cap}" / f"{dom}.json", recs)
    for cap in {c for c, _ in GT}:
        domains = {}
        for (c, dom), rows in GT.items():
            if c != cap:
                continue
            sc = scores.get((c, dom), {})
            domains[dom] = {
                "n_groundtruth": len(rows),
                "missing_prediction_uuids": [u for u, *_ in rows if u not in sc],
                "dialogues": [
                    {
                        "uuid": u,
                        "score": s,
                        "metadata": {"capability": CAP_NAME[c], "domain": dom},
                        "details": {
                            "per_turn": [{"turn_id": 0, "query": "q", "metadata": meta}]
                        },
                    }
                    for u, (s, meta) in sc.items()
                ],
                "summary": {"num_samples": len(rows)},
            }
        _write(
            run / "eval" / f"cap{cap}.json",
            {"capability_name": CAP_NAME[cap], "domains": domains},
        )
    if spans:
        (run / "traces").mkdir(parents=True, exist_ok=True)
        (run / "traces" / "spans-1.jsonl").write_text(
            "".join(json.dumps(s) + "\n" for s in spans)
        )
    if manifest:
        _write(run / "config.json", manifest)
    return run


WRONG = {"exactmatch_score": 0, "answer_score": 0, "groundedness_score": None}
RIGHT = {"exactmatch_score": 1, "answer_score": None, "groundedness_score": 1.0}


@pytest.fixture()
def run_a(tmp_path):
    preds = {
        (2, "hockey"): [
            ("u1", "success", "42", [("get_goals", {"team": "Bruins"})], 2.0),
            ("u2", "success", "5", [("get_goals", {"team": "Leafs"})], 4.0),
            (
                "u3",
                "success",
                "The Habs scored 9 goals",
                [("get_goals", {"team": "habs "})],
                6.0,
            ),
            ("u4", "error", "", [], 300.0),
        ],
        (1, "address"): [
            ("v1", "success", "50010", [("get_zip", {"city": "Ames"})], 1.0)
        ],
    }
    scores = {
        (2, "hockey"): {
            "u1": (1.0, RIGHT),
            "u2": (0.0, WRONG),
            "u3": (0.0, WRONG),
            "u4": (0.0, WRONG),
        },
        (1, "address"): {"v1": (1.0, RIGHT)},
    }
    base = {"vakra.capability_id": 2, "vakra.uuid": "u1", "vakra.run_id": "A"}
    spans = [
        {
            **base,
            "openinference.span.kind": "LLM",
            "llm.token_count.prompt": 100,
            "llm.token_count.completion": 20,
            "llm.token_count.total": 120,
            "start_ns": 1,
        },
        {
            **base,
            "openinference.span.kind": "LLM",
            "llm.token_count.prompt": 150,
            "llm.token_count.completion": 30,
            "llm.token_count.total": 180,
            "start_ns": 3,
        },
        {
            **base,
            "openinference.span.kind": "TOOL",
            "tool.name": "get_goals",
            "input.value": '{"team": "Bruins"}',
            "output.value": '[["42"]]',
            "start_ns": 2,
        },
    ]
    manifest = {
        "run_id": "A",
        "agent_variant": "B0",
        "model": "gpt-oss-120b",
        "git": {"sha": "abc"},
    }
    return make_run(tmp_path / "runs", "run_a", preds, scores, spans, manifest)


@pytest.fixture()
def run_b(tmp_path):
    preds = {
        (2, "hockey"): [
            ("u1", "success", "42", [("get_goals", {"team": "Bruins"})], 2.5),
            ("u2", "success", "10", [("get_wins", {"team": "Leafs"})], 3.0),
            ("u3", "success", "7", [("get_goals", {"team": "Habs"})], 3.0),
            ("u4", "success", "Jones", [("get_coach", {"team": "Jets"})], 3.0),
        ],
        (1, "address"): [
            ("v1", "success", "50010", [("get_zip", {"city": "Ames"})], 1.0)
        ],
    }
    scores = {
        (2, "hockey"): {
            "u1": (1.0, RIGHT),
            "u2": (1.0, RIGHT),
            "u3": (1.0, RIGHT),
            "u4": (0.0, WRONG),
        },
        (1, "address"): {"v1": (1.0, RIGHT)},
    }
    return make_run(
        tmp_path / "runs",
        "run_b",
        preds,
        scores,
        manifest={"run_id": "B", "agent_variant": "B1"},
    )

"""Spans join to a task by the root span's trace_id, not by their own vakra tags."""

import json

from capstone.analysis.loader import load_run


def _pred(uuid, answer="42"):
    return {
        "uuid": uuid,
        "domain": "hockey",
        "status": "success",
        "error": "",
        "output": [
            {
                "turn_id": 0,
                "query": "q",
                "answer": answer,
                "sequence": {"tool_call": []},
            }
        ],
    }


def test_llm_span_without_vakra_attributes_joins_by_trace_id(tmp_path):
    run = tmp_path / "run"
    (run / "cap2").mkdir(parents=True)
    (run / "traces").mkdir()
    (run / "cap2" / "hockey.json").write_text(
        json.dumps([_pred("u1"), _pred("u2", "7")]), encoding="utf-8"
    )
    spans = [
        {
            "name": "vakra.task",
            "trace_id": "tr-1",
            "vakra.capability_id": 2,
            "vakra.uuid": "u1",
        },
        {
            "trace_id": "tr-1",
            "openinference.span.kind": "LLM",
            "llm.token_count.prompt": 10,
            "llm.token_count.completion": 1,
            "llm.token_count.total": 11,
        },
        {
            "trace_id": "tr-other",
            "openinference.span.kind": "LLM",
            "llm.token_count.prompt": 99,
            "vakra.capability_id": 2,
            "vakra.uuid": "u1",
        },
        {
            "openinference.span.kind": "LLM",
            "llm.token_count.prompt": 77,
            "vakra.capability_id": 2,
            "vakra.uuid": "u1",
        },
        {
            "name": "vakra.task",
            "trace_id": "tr-2",
            "vakra.capability_id": 2,
            "vakra.uuid": "u2",
        },
        {
            "trace_id": "tr-2",
            "openinference.span.kind": "LLM",
            "llm.token_count.prompt": 5,
            "llm.token_count.completion": 4,
            "llm.token_count.total": 9,
            "vakra.capability_id": 9,
            "vakra.uuid": "nope",
        },
    ]
    (run / "traces" / "spans-1.jsonl").write_text(
        "".join(json.dumps(s) + "\n" for s in spans), encoding="utf-8"
    )
    items = load_run(run).by_key()
    u1, u2 = items[(2, "u1")], items[(2, "u2")]
    assert (u1.prompt_tokens, u1.completion_tokens, u1.n_llm_calls) == (10, 1, 1)
    assert (u2.prompt_tokens, u2.completion_tokens, u2.n_llm_calls) == (5, 4, 1)

"""B1 value extraction, evidence tracing, verifier paths and the judge parser
(offline: no model, no MCP)."""

import json

import pytest

from capstone.b1.config import JudgeConfig, VerifierConfig
from capstone.b1.evidence import EvidenceIndex
from capstone.b1.judge import PROMPT_SHA256, JudgeResult, build_judge, parse_judge_reply, render_prompt
from capstone.b1.step import B1Step, input_from_record, verifier_error
from capstone.b1.values import extract_answer_values, normalize_text, numbers_in_text
from capstone.b1.verifier import ToolOutput, VerifierInput, is_abstention, verify

NO_JUDGE = VerifierConfig(judge=JudgeConfig(enabled=False))


def kinds(text):
    return [(v.kind, v.norm) for v in extract_answer_values(text).values]


class FakeJudge:
    model = "fake-judge"

    def __init__(self, verdict="supported", claim="", error=None):
        self.verdict, self.claim, self.error = verdict, claim, error
        self.calls = []

    def __call__(self, *, query, evidence, answer):
        self.calls.append({"query": query, "evidence": evidence, "answer": answer})
        return JudgeResult(verdict=self.verdict, unsupported_claim=self.claim,
                           model=self.model, error=self.error)


def vin(answer, outputs, **kw):
    return VerifierInput(query=kw.pop("query", "q"), answer=answer,
                         tool_outputs=[ToolOutput(n, o) for n, o in outputs], **kw)


# -- values -------------------------------------------------------------------

def test_extract_numbers_units_and_precision():
    (v,) = extract_answer_values("The total is 1,234.5 km").values
    assert (v.kind, v.norm, v.unit) == ("number", "1234.5", "km")
    assert v.lo == pytest.approx(1234.45) and v.hi == pytest.approx(1234.55)
    (p,) = extract_answer_values("45%").values
    assert p.unit == "percent" and (0.445, 0.455) == pytest.approx(p.alts[0])
    (m,) = extract_answer_values("Revenue was $3.2 million").values  # sentence start is not a name
    assert (m.norm, m.unit) == ("3.2e+06", "usd")
    assert kinds("-3.5") == [("number", "-3.5")]


def test_extract_dates_ids_and_skips():
    assert kinds("On March 5, 2021 and 2020-01-02") == [("date", "2021-03-05"), ("date", "2020-01-02")]
    ex = extract_answer_values("Player ID AB1234 scored 12th")
    assert [(v.kind, v.norm) for v in ex.values] == [("id", "ab1234")] and ex.skipped == ["12th"]
    # number+unit runs are numbers, not ids
    assert kinds("5km and 10am") == [("number", "5"), ("number", "10")]
    ex = extract_answer_values("1. Alpha\n2. Beta")
    assert kinds("1. Alpha\n2. Beta") == [("name", "alpha"), ("name", "beta")] and ex.skipped == ["1.", "2."]


def test_extract_names():
    assert kinds("The coach is Smith.") == [("name", "smith")]
    assert kinds("Paris") == [("name", "paris")]
    assert kinds("None, Charles") == [("name", "charles")]


def test_normalize_and_tool_numbers():
    assert normalize_text("  Café  “Señor”  ") == 'cafe "senor"'
    assert numbers_in_text('[["36526.0", -4]]') == [36526.0, -4.0]
    # "1,200" in tool text is read both ways (thousands, or a compact list)
    assert numbers_in_text("1,200") == [1200.0, 1.0, 200.0]


def test_extraction_scales_to_long_lists():
    answer = ", ".join(f"Place Number{i}" for i in range(5000))
    assert len(extract_answer_values(answer).values) == 5000


def test_extraction_is_linear_in_sentence_starts():
    import time

    answer = "Revenue was fine. " * 40_000  # ~720k chars of one-word sentence starts
    t0 = time.perf_counter()
    assert extract_answer_values(answer).values == []
    assert time.perf_counter() - t0 < 5.0


# -- evidence -----------------------------------------------------------------

def test_evidence_counts_and_sources():
    idx = EvidenceIndex.build([("get_rows", [["a"], ["b"], ["a"]])], query="top 5 teams")
    n = extract_answer_values("3").values[0]
    assert idx.trace(n).via == "derived:count"
    d = extract_answer_values("2").values[0]
    assert idx.trace(d).via == "derived:count_distinct"
    q = extract_answer_values("5").values[0]
    assert idx.trace(q).evidence_id == "q"
    assert EvidenceIndex.build([("t", [["a"], ["b"]])], derivations="none").trace(n) is None


def test_evidence_simple_derivations():
    idx = EvidenceIndex.build([("t", [[10], [30]])], derivations="simple")
    for text, op in (("40", "sum"), ("20", "mean"), ("3", "ratio"), ("200%", "percent_change")):
        tr = idx.trace(extract_answer_values(text).values[0])
        assert tr is not None and tr.via.startswith("derived:"), (text, op)


def test_evidence_phrase_boundaries():
    idx = EvidenceIndex.build([("t", "Bob Smithson; AB12345")])
    assert idx.trace(extract_answer_values("Smith").values[0]) is None
    assert idx.trace(extract_answer_values("Bob Smithson").values[0]) is not None
    assert idx.trace(extract_answer_values("AB1234").values[0]) is None


# -- verifier paths -----------------------------------------------------------

def test_deterministic_accept_and_reject():
    out = [("get_goals", '[["42"]]')]
    v = verify(vin("The Bruins scored 42 goals", out), NO_JUDGE)
    assert (v.outcome, v.b1_path, v.reason, v.status) == ("accept", "deterministic", "all_traced", "passed")
    assert v.evidence_ids == ["t0:get_goals"] and v.n_tool_outputs == 1
    v = verify(vin("The Bruins scored 43 goals", out), NO_JUDGE)
    assert (v.outcome, v.reason, v.failed_field, v.status) == ("reject", "untraced_value", "43", "failed")


def test_scale_suffix_matches_suffixed_or_scaled_tool_values():
    # gold false alarm (cap4 app_store): the tool returns the same "6.6M" string
    assert verify(vin("6.6M, 20", [("t", '[["6.6M", 20]]')]), NO_JUDGE).outcome == "accept"
    assert verify(vin("6.6M, 20", [("t", "[[6600000, 20]]")]), NO_JUDGE).outcome == "accept"
    assert verify(vin("6.7M, 20", [("t", '[["6.6M", 20]]')]), NO_JUDGE).outcome == "reject"
    # gold false alarm (cap3 restaurant): "# 4b" is a suite number, not 4 billion
    assert verify(vin("moorpark ave # 4b", [("t", '[["moorpark ave # 4b"]]')]), NO_JUDGE).outcome == "accept"


def test_float_precision_tolerance():
    out = [("t", "[[1.2649]]")]
    assert verify(vin("about 1.26", out), NO_JUDGE).outcome == "accept"
    assert verify(vin("1.27", out), NO_JUDGE).outcome == "reject"


def test_insufficient_paths():
    assert verify(vin("", []), NO_JUDGE).reason == "no_answer"
    assert verify(vin("42", [], status="error", error="timeout"), NO_JUDGE).reason == "agent_error"
    v = verify(VerifierInput(query="q", answer="42", tool_outputs=None), NO_JUDGE)
    assert (v.outcome, v.reason) == ("insufficient_evidence", "tool_outputs_unknown")


def test_names_go_to_judge():
    out = [("get_coach", '[["Smith"]]')]
    assert verify(vin("Smith", out), NO_JUDGE).reason == "names_traced"
    assert verify(vin("Smith and Jones", [("t", '[["Smith"], ["Jones"]]')]), NO_JUDGE).reason == "names_traced"
    j = FakeJudge("unsupported", claim="Jones")
    v = verify(vin("Jones", out), VerifierConfig(), j)
    assert (v.outcome, v.b1_path, v.reason, v.failed_field) == ("reject", "judge", "judge_unsupported", "Jones")
    assert "[t0:get_coach]" in j.calls[0]["evidence"] and "gold" not in json.dumps(j.calls[0]).lower()
    v = verify(vin("Jones", out), NO_JUDGE)
    assert (v.outcome, v.b1_path, v.reason) == ("insufficient_evidence", "judge", "judge_unavailable")
    v = verify(vin("Jones", out), VerifierConfig(names_missing="reject"), j)
    assert (v.outcome, v.b1_path, v.reason) == ("reject", "deterministic", "names_missing")


def test_free_text_judge_outcomes():
    out = [("t", '[["ok"]]')]
    text = "it looks fine overall"
    assert verify(vin(text, out), VerifierConfig(), FakeJudge("supported")).reason == "judge_supported"
    assert verify(vin(text, out), VerifierConfig(), FakeJudge("insufficient")).reason == "judge_insufficient"
    v = verify(vin(text, out), VerifierConfig(), FakeJudge("insufficient", error="ConnectError"))
    assert v.reason == "judge_unavailable"


def test_abstention_accepted_without_judge():
    assert is_abstention("I could not find any matching records.")
    assert is_abstention("I can not answer.")  # the cap4 gold abstention string
    j = FakeJudge()
    v = verify(vin("I could not find any matching records.", [("t", "[]")]), VerifierConfig(), j)
    assert (v.outcome, v.reason) == ("accept", "abstention") and not j.calls


def test_reject_policy_abstain():
    cfg = VerifierConfig(on_reject="abstain", judge=JudgeConfig(enabled=False))
    v = verify(vin("43", [("t", "[[42]]")]), cfg)
    assert v.action == "abstained" and v.original_answer == "43" and v.answer_returned == cfg.abstain_text
    v = verify(vin("42", [("t", "[[42]]")]), cfg)
    assert v.action == "kept" and v.answer_returned == "42"


def test_config_hash_and_file(tmp_path):
    a, b = VerifierConfig(), VerifierConfig(derivations="none")
    assert a.sha256() != b.sha256() and len(a.sha256()) == 16
    p = tmp_path / "v.json"
    p.write_text(b.model_dump_json())
    assert VerifierConfig.load(p) == b
    with pytest.raises(ValueError):
        VerifierConfig.model_validate({"bogus": 1})


def test_shipped_verifier_config_is_default():
    from pathlib import Path

    shipped = Path(__file__).resolve().parents[1] / "run" / "configs" / "b1_verifier.json"
    assert VerifierConfig.load(shipped) == VerifierConfig()


# -- judge --------------------------------------------------------------------

def test_parse_judge_reply():
    assert parse_judge_reply('{"verdict": "Supported", "reason": "ok"}') == ("supported", "", "ok")
    assert parse_judge_reply('<think>{"verdict":"supported"}</think> {"verdict": "unsupported", '
                             '"unsupported_claim": "43"}')[:2] == ("unsupported", "43")
    assert parse_judge_reply("The answer is unsupported.")[0] == "unsupported"
    assert parse_judge_reply("???")[0] == "insufficient"


def test_judge_prompt_and_build():
    p = render_prompt(query="Q?", evidence="[t0:x] 1", answer="A")
    assert "Q?" in p and "[t0:x] 1" in p and len(PROMPT_SHA256) == 16
    assert build_judge(JudgeConfig(enabled=False)) is None


# -- step ---------------------------------------------------------------------

def test_input_from_record_and_step():
    rec = {"query": "goals?", "answer": "42", "status": "success", "error": "",
           "initial_data": {"rows": 1},
           "tool_calls": [{"name": "get_goals", "arguments": {}, "result": '[["42"]]'}],
           "context": [{"role": "user", "content": "earlier"}]}
    inp = input_from_record(rec)
    assert [t.name for t in inp.tool_outputs] == ["get_data", "get_goals"] and inp.context == "user: earlier"
    assert input_from_record({k: v for k, v in rec.items() if k != "tool_calls"}).tool_outputs is None
    step = B1Step(NO_JUDGE, None)
    assert step(rec).outcome == "accept"
    d = step.describe()
    assert d["config_sha256"] == NO_JUDGE.sha256() and d["judge_prompt_sha256"] == PROMPT_SHA256


def test_step_never_loses_answer(monkeypatch):
    import capstone.b1.step as S

    def boom(*a, **k):
        raise RuntimeError("bad")

    monkeypatch.setattr(S, "verify", boom)
    v = S.B1Step(NO_JUDGE, None)({"answer": "42", "tool_calls": []})
    assert (v.outcome, v.reason, v.answer_returned) == ("insufficient_evidence", "verifier_error", "42")
    assert verifier_error({"answer": "x"}, NO_JUDGE, ValueError("e")).error == "ValueError: e"


def test_number_trace_stops_at_first_direct_hit():
    # 200k equal numbers: the trace must not walk all of them (it used to, on huge tool dumps).
    idx = EvidenceIndex.build([("t", [[7]] * 200_000)], query="give me 7")
    n = next(v for v in extract_answer_values("It is 7.").values if v.kind == "number")
    tr = idx.trace(n)
    assert tr is not None and tr.via == "direct" and tr.evidence_id == "t0:t"

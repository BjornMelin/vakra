"""B2 trigger, caps, policies, and the unfrozen config. No model and no network."""

import asyncio
import json
from pathlib import Path

import pytest

from capstone.b1.config import JudgeConfig, VerifierConfig
from capstone.b1.step import B1Step
from capstone.b2.config import B2Config, B2ConfigError
from capstone.b2.control import control_trigger_ids
from capstone.b2.executor import AgentRecoveryExecutor, RecoveryAttempt, recovery_recursion_limit
from capstone.b2.step import B2Step

UNFROZEN = Path(__file__).resolve().parents[1] / "run" / "configs" / "b2_unfrozen.json"
NO_JUDGE = VerifierConfig(
    on_reject="flag",
    on_insufficient="flag",
    judge=JudgeConfig(enabled=False),
)


def _cfg(**over):
    base = dict(
        status="SET",
        arm="b1_reject",
        recovery_step_cap=1,
        max_recovery_tool_calls=3,
        max_recovery_llm_calls=4,
        recovery_timeout_s=30,
        max_resume_prompt_tokens=65536,
        prompt_token_count_method="chars_div_4",
        control_seed=None,
        matched_trigger_count=None,
        on_reject="flag_keep_original",
        on_cap_hit="flag_keep_original",
        on_error="flag_keep_original",
        on_insufficient="abstain",
    )
    base.update(over)
    cfg = B2Config.model_validate(base)
    cfg.validate_launch()
    return cfg


def _b1():
    return B1Step(NO_JUDGE, None)


def _record(uuid="u1", answer="99", result="42"):
    return {
        "uuid": uuid,
        "domain": "d",
        "query": "How many?",
        "answer": answer,
        "status": "success",
        "error": "",
        "tool_calls": [{"name": "t", "arguments": {}, "result": result}],
    }


class FakeExec:
    def __init__(self, answers, tool_calls=None, llm_calls=1, delay=0, error=None):
        self.answers = list(answers)
        self.tool_calls = tool_calls if tool_calls is not None else [
            {"name": "t", "arguments": {}, "result": "42"}
        ]
        self.llm_calls = llm_calls
        self.delay = delay
        self.error = error
        self.calls = 0

    async def attempt(self, **kwargs):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise RuntimeError(self.error)
        answer = self.answers[min(self.calls - 1, len(self.answers) - 1)]
        return RecoveryAttempt(
            answer=answer, tool_calls=list(self.tool_calls), llm_calls=self.llm_calls
        )


def _step(exec=None, **over):
    return B2Step(_cfg(**over), _b1(), executor=exec)


def _run(step, record):
    return asyncio.run(step.decide(record))


def test_unfrozen_file_refuses_and_proposed_values_are_not_live():
    raw = json.loads(UNFROZEN.read_text())
    assert raw["status"] == "UNFROZEN"
    assert raw["max_recovery_tool_calls"] is None
    assert raw["control_seed"] is None
    assert raw["proposed"]["max_recovery_tool_calls"] == 3
    assert raw["proposed"]["max_recovery_llm_calls"] == 4
    assert raw["proposed"]["recovery_timeout_s"] == 300
    assert raw["proposed"]["max_resume_prompt_tokens"] == 65536
    assert raw["proposed"]["control_seed"] == 20261119
    assert raw["proposed"]["on_reject"] == "flag_keep_original"
    assert raw["proposed"]["on_insufficient"] == "abstain"
    with pytest.raises(B2ConfigError, match="UNFROZEN"):
        B2Config.load(UNFROZEN)
    copied = dict(raw)
    copied["max_recovery_tool_calls"] = raw["proposed"]["max_recovery_tool_calls"]
    with pytest.raises(B2ConfigError, match="UNFROZEN"):
        B2Config.model_validate(copied).validate_launch()


def test_unset_field_refuses_even_if_proposed_has_the_number():
    raw = _cfg().model_dump()
    raw["max_recovery_tool_calls"] = None
    raw["proposed"] = {"max_recovery_tool_calls": 3}
    with pytest.raises(B2ConfigError, match="max_recovery_tool_calls"):
        B2Config.model_validate(raw).validate_launch()


def test_reject_runs_one_attempt_then_stops_and_keeps_b0_answer():
    exe = FakeExec(["7"])
    step = _step(exe, recovery_step_cap=1, on_reject="flag_keep_original")
    verdict, decision = _run(step, _record())
    assert exe.calls == 1
    assert decision["triggered"] is True
    assert decision["recovery_attempted"] is True
    assert decision["n_recovery_tool_calls"] == 1
    assert decision["recovery_tool_calls"][0]["name"] == "t"
    assert decision["final_answer_changed"] is False
    assert decision["abstained"] is False
    assert decision["stop_reason"] == "rejected"
    assert decision["policy_applied"] == "flag_keep_original"
    assert verdict.answer_returned == "99"
    assert verdict.action == "kept"


def test_cap_two_allows_a_second_attempt_and_not_a_third():
    exe = FakeExec(["7", "42"])
    step = _step(exe, recovery_step_cap=2)
    verdict, decision = _run(step, _record())
    assert exe.calls == 2
    assert decision["stop_reason"] == "accepted"
    assert decision["final_answer_changed"] is True
    assert decision["abstained"] is False
    assert verdict.answer_returned == "42"


def test_accept_on_first_attempt_does_not_use_the_rest_of_the_cap():
    exe = FakeExec(["42", "7"])
    step = _step(exe, recovery_step_cap=2)
    verdict, decision = _run(step, _record())
    assert exe.calls == 1
    assert decision["final_answer_changed"] is True
    assert verdict.answer_returned == "42"


def test_accept_is_not_triggered_on_the_b1_reject_arm():
    exe = FakeExec(["7"])
    step = _step(exe)
    _, decision = _run(step, _record(answer="42"))
    assert exe.calls == 0
    assert decision["triggered"] is False
    assert decision["abstained"] is False
    assert decision["final_answer_changed"] is False


def test_insufficient_recheck_abstains():
    exe = FakeExec([""], tool_calls=[])
    step = _step(exe, on_insufficient="abstain")
    verdict, decision = _run(step, _record())
    assert decision["recheck_outcome"] == "insufficient_evidence"
    assert decision["abstained"] is True
    assert decision["final_answer_changed"] is True
    assert decision["policy_applied"] == "abstain"
    assert verdict.action == "abstained"
    assert verdict.answer_returned == NO_JUDGE.abstain_text


def test_cap_hit_and_error_keep_the_original_answer():
    over = FakeExec(["42"], tool_calls=[{"name": "t", "arguments": {}, "result": "42"}] * 4)
    step = _step(over, max_recovery_tool_calls=3, on_cap_hit="flag_keep_original")
    verdict, decision = _run(step, _record())
    assert decision["stop_reason"] == "cap_hit"
    assert decision["abstained"] is False
    assert verdict.answer_returned == "99"
    assert decision["n_recovery_tool_calls"] == 4

    boom = FakeExec(["42"], error="mcp down")
    step = _step(boom, on_error="flag_keep_original")
    verdict, decision = _run(step, _record())
    assert decision["stop_reason"] == "error"
    assert verdict.answer_returned == "99"
    assert decision["abstained"] is False


def test_timeout_is_a_cap_hit():
    exe = FakeExec(["42"], delay=1)
    step = _step(exe, recovery_timeout_s=0.05, on_cap_hit="flag_keep_original")
    verdict, decision = _run(step, _record())
    assert decision["stop_reason"] == "cap_hit"
    assert verdict.answer_returned == "99"
    assert decision["recovery_attempted"] is True
    assert decision["n_recovery_tool_calls"] == 0


def test_resume_prompt_over_the_token_cap_skips_recovery():
    exe = FakeExec(["42"])
    step = _step(exe, max_resume_prompt_tokens=1)
    _, decision = _run(step, _record())
    assert exe.calls == 0
    assert decision["triggered"] is True
    assert decision["recovery_attempted"] is False
    assert decision["skip_reason"] == "resume_prompt_tokens"
    assert decision["final_answer_changed"] is False
    assert decision["abstained"] is False
    assert decision["n_recovery_tool_calls"] == 0


def test_control_arm_matches_count_and_is_seed_stable():
    universe = [f"u{i}" for i in range(20)]
    a = control_trigger_ids(universe, 5, 20261119)
    b = control_trigger_ids(list(reversed(universe)), 5, 20261119)
    c = control_trigger_ids(universe, 5, 1)
    assert a == b
    assert len(a) == 5
    assert a != c
    with pytest.raises(B2ConfigError, match="exceeds"):
        control_trigger_ids(universe, 21, 20261119)

    chosen = control_trigger_ids(["keep", "flip"], 1, 7)
    exe = FakeExec(["7"])
    step = B2Step(
        _cfg(
            arm="random_control",
            control_seed=7,
            matched_trigger_count=1,
        ),
        _b1(),
        task_ids=["keep", "flip"],
        executor=exe,
    )
    assert step.triggers == chosen
    triggered_id = next(iter(chosen))
    other = "flip" if triggered_id == "keep" else "keep"
    # The triggered task is accepted by B1 (answer traces). The control still fires.
    _run(step, _record(uuid=triggered_id, answer="42"))
    assert exe.calls == 1
    before = exe.calls
    _, decision = _run(step, _record(uuid=other, answer="99"))
    assert exe.calls == before
    assert decision["triggered"] is False


def test_missing_executor_refuses_instead_of_skipping():
    step = _step(None)
    with pytest.raises(B2ConfigError, match="no executor"):
        _run(step, _record())


def test_recovery_recursion_budget_tracks_the_caps():
    assert recovery_recursion_limit(3, 4) == 7
    assert recovery_recursion_limit(0, 4) == 1
    assert recovery_recursion_limit(5, 2) == 3


def test_decision_is_logged_on_the_span_and_the_trajectory_record():
    from capstone.observability.tracing import TaskSpan
    from capstone.trajectories import build_record

    class Span:
        def __init__(self):
            self.attrs = {}

        def set_attributes(self, attrs):
            self.attrs.update(attrs)

        def set_status(self, status):
            self.status = status

    span = Span()
    TaskSpan(span).record_verification(
        {
            "outcome": "reject",
            "b1_path": "deterministic",
            "reason": "untraced_value",
            "duration_s": 0.1,
            "action": "kept",
            "b2": {
                "triggered": True,
                "n_recovery_tool_calls": 2,
                "final_answer_changed": False,
                "abstained": False,
            },
        }
    )
    assert span.attrs["vakra.b2.triggered"] is True
    assert span.attrs["vakra.b2.recovery_tool_calls"] == 2
    assert span.attrs["vakra.b2.final_answer_changed"] is False
    assert span.attrs["vakra.b2.abstained"] is False

    plain = build_record(
        uuid="u", domain="d", query="q", answer="99", tool_calls=[]
    )
    assert "b2" not in plain
    logged = build_record(
        uuid="u",
        domain="d",
        query="q",
        answer="99",
        tool_calls=[],
        b2={"triggered": True, "n_recovery_tool_calls": 1, "final_answer_changed": False, "abstained": False},
    )
    assert logged["b2"]["triggered"] is True
    assert logged["b2"]["abstained"] is False


def test_live_executor_passes_the_recursion_budget():
    class Agent:
        def __init__(self):
            self.limits = []

        async def run(self, prompt, additional_instructions=None, *, recursion_limit=None):
            self.limits.append(recursion_limit)
            return type("R", (), {
                "content": "42",
                "tool_calls": [{"tool_name": "t", "arguments": {}, "result": "42"}],
                "trajectory": [{"type": "AIMessage"}, {"type": "ToolMessage"}, {"type": "AIMessage"}],
            })()

    agent = Agent()
    attempt = asyncio.run(
        AgentRecoveryExecutor(agent).attempt(
            prompt="p", max_tool_calls=3, max_llm_calls=4, timeout_s=5
        )
    )
    assert agent.limits == [7]
    assert attempt.llm_calls == 2
    assert attempt.tool_calls[0]["name"] == "t"

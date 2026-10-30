"""B1 offline pipeline: sidecars, loader, replay, collect (fake MCP), labels,
verdict-vs-gold eval, gold check, runner helpers, manifest and the CLI."""

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from capstone.analysis.labels import NOT_SUPPORTED, SUPPORTED_BUT_WRONG, auto_label, label_rows
from capstone.analysis.loader import load_run
from capstone.b1.cli import main as b1_main
from capstone.b1.config import JudgeConfig, VerifierConfig
from capstone.b1.replay import replay_run
from capstone.b1.seeded import FAKE_ENTITY, gold_check, iter_gold, perturb, render_answer
from capstone.b1.step import B1Step
from capstone.b1.verifier_eval import evaluate_verdicts, markdown
from capstone.trajectories import build_record, read_trajectories, trajectory_path, write_trajectories

NO_JUDGE = VerifierConfig(judge=JudgeConfig(enabled=False))
FIXTURE = Path(__file__).parent / "fixtures" / "b1_gold_sample.json"
CAP_DIRS = {"1": "capability_1_bi_apis", "2": "capability_2_dashboard_apis",
            "3": "capability_3_multihop_reasoning", "4": "capability_4_multiturn"}


def _traj(uuid, domain, answer, result, name="get_goals", **kw):
    return build_record(uuid=uuid, domain=domain, query="q", answer=answer,
                        tool_calls=[{"tool_name": name, "arguments": {}, "result": result}], **kw)


@pytest.fixture()
def tool_outputs(tmp_path):
    """Sidecars kept outside the run (what ``collect`` writes)."""
    root = tmp_path / "collected"
    write_trajectories([_traj("u2", "hockey", "5", '[["5"]]'),
                        _traj("u3", "hockey", "The Habs scored 9 goals", '[["7"]]')],
                       trajectory_path(root / "cap2", "hockey"))
    write_trajectories([_traj("v1", "address", "50010", '[["50010"]]', name="get_zip",
                              initial_data={"zip": [50010]})],
                       trajectory_path(root / "cap1", "address"))
    return root


@pytest.fixture()
def gold_sample(tmp_path):
    """A few real train-split gold records (copied; the source files are never touched)."""
    root = tmp_path / "gold"
    for cap, recs in json.loads(FIXTURE.read_text()).items():
        by_domain = {}
        for r in recs:
            by_domain.setdefault(r["domain"], []).append(r)
        for dom, rs in by_domain.items():
            p = root / CAP_DIRS[cap] / "output" / f"{dom}.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(rs))
    return root


# -- sidecars + loader --------------------------------------------------------

def test_trajectory_roundtrip(tmp_path):
    rec = build_record(uuid="x", domain="d", query="q", answer="a",
                       tool_calls=[{"tool_name": "t", "arguments": {"a": 1},
                                    "result": [{"type": "text", "text": "out"}]}],
                       context=[{"role": "user", "content": "hi"}])
    assert rec["tool_calls"] == [{"name": "t", "arguments": {"a": 1}, "result": "out", "result_truncated": False}]
    p = trajectory_path(tmp_path, "d")
    write_trajectories([rec], p)
    assert read_trajectories(p)["x"]["context"] == [{"role": "user", "content": "hi"}]
    assert read_trajectories(tmp_path / "missing.json") == {}


def test_loader_attaches_sidecars(run_a, tool_outputs):
    run = load_run(run_a, tool_outputs_dir=tool_outputs)
    items = run.by_key()
    assert items[(2, "u3")].tool_outputs == ['[["7"]]'] and items[(2, "u3")].tool_outputs_source == "trajectory"
    assert items[(2, "u1")].tool_outputs_source == "spans"
    assert items[(2, "u4")].tool_outputs_source is None
    assert "tool_calls" not in items[(2, "u4")].trajectory_record()
    # the run's own sidecar overrides the collected one
    write_trajectories([_traj("u3", "hockey", "x", '[["9"]]')], trajectory_path(run_a / "cap2", "hockey"))
    assert load_run(run_a, tool_outputs_dir=tool_outputs).by_key()[(2, "u3")].tool_outputs == ['[["9"]]']


def test_sidecars_are_not_predictions(run_a, tool_outputs):
    from capstone.run.manifest import count_predictions

    before = count_predictions(run_a)
    shutil.copytree(tool_outputs / "cap2", run_a / "cap2", dirs_exist_ok=True)
    assert count_predictions(run_a) == before
    assert {it.uuid for it in load_run(run_a).items if it.has_prediction} == {"u1", "u2", "u3", "u4", "v1"}


# -- replay + eval ------------------------------------------------------------

def test_replay_flag_mode(run_a, tool_outputs, gt_root, tmp_path):
    out = tmp_path / "b1_replay"
    s = replay_run(run_a, out, B1Step(NO_JUDGE, None), tool_outputs_dir=tool_outputs)
    assert s.n_tasks == 5 and s.n_answers_changed == 0
    assert s.eval_copied == [1, 2] and s.needs_rescore == []
    assert s.outcomes[("deterministic", "accept")] == 3  # u1 (spans), u2 (faithful, wrong tool), v1
    assert s.outcomes[("deterministic", "reject")] == 1  # u3: 9 vs tool 7
    assert s.outcomes[("deterministic", "insufficient_evidence")] == 1  # u4 agent error
    cfg = json.loads((out / "config.json").read_text())
    assert cfg["agent_variant"] == "B1" and cfg["replay_of"]["agent_variant"] == "B0"
    assert cfg["b1"]["config_sha256"] == NO_JUDGE.sha256() and "replayed_at" in cfg["timestamps"]
    # source run untouched; replay is idempotent only into a fresh dir
    assert not list((run_a / "cap2").glob("*_trajectory.json"))
    with pytest.raises(FileExistsError):
        replay_run(run_a, out, B1Step(NO_JUDGE, None))
    with pytest.raises(ValueError):
        replay_run(run_a, run_a, B1Step(NO_JUDGE, None))

    run = load_run(out, gt_root=gt_root)
    v = run.by_key()[(2, "u3")].verification
    assert (v["outcome"], v["b1_path"], v["failed_field"]) == ("reject", "deterministic", "9")

    ev = evaluate_verdicts(run)
    allrow = next(r for r in ev.cells if r["capability"] == "all" and r["b1_path"] == "all")
    assert (allrow["n"], allrow["accept_correct"], allrow["accept_wrong"],
            allrow["reject_wrong"], allrow["insufficient_wrong"]) == (5, 2, 1, 1, 1)
    assert allrow["false_alarm_rate"] == 0.0 and allrow["catch_rate"] == pytest.approx(1 / 3, abs=1e-4)
    heads = {(r["headline"], r["subreason"]): r for r in ev.catch_by_headline}
    assert heads[(NOT_SUPPORTED, "wrong_tool")]["accepted"] == 1  # wrong tool, faithfully reported
    assert "B1 verdicts vs gold" in markdown(ev)


def test_replay_abstain_mode_needs_rescore(run_a, tool_outputs, tmp_path):
    cfg = VerifierConfig(on_reject="abstain", judge=JudgeConfig(enabled=False))
    out = tmp_path / "b1_abstain"
    s = replay_run(run_a, out, B1Step(cfg, None), tool_outputs_dir=tool_outputs)
    assert s.n_answers_changed == 1 and s.needs_rescore == [2] and s.eval_copied == [1]
    preds = {r["uuid"]: r for r in json.loads((out / "cap2" / "hockey.json").read_text())}
    assert preds["u3"]["output"][-1]["answer"] == cfg.abstain_text
    traj = read_trajectories(trajectory_path(out / "cap2", "hockey"))
    assert traj["u3"]["answer"] == "The Habs scored 9 goals"  # the agent's own answer is kept
    assert not (out / "eval" / "cap2.json").exists()


# -- labels -------------------------------------------------------------------

def test_labels_use_b1_verdicts(run_a, tool_outputs, gt_root, tmp_path):
    out = tmp_path / "r"
    replay_run(run_a, out, B1Step(NO_JUDGE, None), tool_outputs_dir=tool_outputs)
    items = load_run(out, gt_root=gt_root).by_key()
    lab = auto_label(items[(2, "u3")])
    assert (lab.headline, lab.subreason, lab.rule) == (NOT_SUPPORTED, "answer_not_in_output", "b1_deterministic")
    assert auto_label(items[(2, "u2")]).subreason == "wrong_tool"
    its = list(items.values())
    rows = {r["uuid"]: r for r in label_rows(its, {it.key: auto_label(it) for it in its})}
    assert rows["u3"]["b1_outcome"] == "reject" and rows["u3"]["b1_path"] == "deterministic"
    assert auto_label(items[(2, "u3")], use_b1=False).rule != "b1_deterministic"


def test_every_wrong_answer_gets_a_headline(run_a, tool_outputs, gt_root):
    run = load_run(run_a, gt_root=gt_root, tool_outputs_dir=tool_outputs)
    for it in run.items:
        if it.scored and (it.score or 0) < 1.0:
            lab = auto_label(it)
            assert lab.headline in (NOT_SUPPORTED, SUPPORTED_BUT_WRONG) and lab.subreason, it.uuid


# -- collect (fake MCP session) -----------------------------------------------

class FakeSession:
    def __init__(self, outputs):
        self.outputs, self.calls = outputs, []

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(
            name="get_zip", inputSchema={"type": "object", "properties": {"city": {"type": "string"}}})])

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name not in self.outputs:
            raise RuntimeError(f"no tool {name}")
        return SimpleNamespace(content=[SimpleNamespace(text=self.outputs[name])])


def test_collect_reexecutes_like_the_evaluator(run_a):
    from capstone.b1.collect import collect_domain

    records = json.loads((run_a / "cap1" / "address.json").read_text())
    records[0]["output"][0]["sequence"]["tool_call"].append({"name": "missing", "arguments": "{}"})
    session = FakeSession({"get_data": '{"zip": [50010]}', "get_zip": '[["50010"]]'})
    (rec,) = asyncio.run(collect_domain(session, records, capability=1))
    assert session.calls[0] == ("get_data", {"tool_universe_id": "v1"})
    assert rec["initial_data"] == {"zip": [50010]} and rec["tool_outputs_source"] == "reexecuted"
    assert [c["result"] for c in rec["tool_calls"]] == ['[["50010"]]', "Error: no tool missing"]
    assert B1Step(NO_JUDGE, None)(rec).outcome == "accept"


# -- gold check + seeded errors -----------------------------------------------

def test_perturbations():
    import random

    rng = random.Random(0)
    assert perturb("The total is 100", "number_shift", rng) == "The total is 144"
    assert perturb("on 2020-01-02", "date_shift", rng) == "on 2021-02-02"  # 2020 is a leap year
    swapped = perturb("id AB1234", "id_swap", rng)
    assert swapped != "id AB1234" and swapped.startswith("id AB")
    assert perturb("The coach is Smith.", "entity_swap", rng) == f"The coach is {FAKE_ENTITY}."
    assert perturb("no values here", "date_shift", rng) is None
    assert render_answer([["a", 1], ["b"]]) == "a, 1, b" and render_answer(None) == ""


def test_gold_check_on_real_gold_sample(gold_sample):
    cases = list(iter_gold(gold_sample, (1, 2, 3, 4)))
    assert len(cases) == 12 and any(c.context for c in cases if c.capability == 4)
    rep = gold_check(gold_sample, NO_JUDGE)
    rows = {r["key"]: r for r in rep.rows()}
    assert rows["all:gold"]["n"] == 12
    assert rows["all:gold"]["false_alarm_rate"] == 0.0, rep.false_alarms
    assert rows["all:number_shift"]["detection_rate"] == 1.0, rep.misses
    assert rows["all:entity_swap"]["judge"] >= 1  # names go to the judge by default
    strict = gold_check(gold_sample, VerifierConfig(names_missing="reject", judge=JudgeConfig(enabled=False)))
    assert {r["key"]: r for r in strict.rows()}["all:entity_swap"]["detection_rate"] == 1.0
    big = gold_check(gold_sample, NO_JUDGE, max_file_bytes=10)
    assert big.skipped_files and not big.rows()


# -- runner helpers / manifest / tracing ---------------------------------------

def test_runner_helpers_trajectory_log(tmp_path):
    from benchmark.runner_helpers import BenchmarkResult, save_trajectory_log

    r = BenchmarkResult(uuid="u", domain="d", query="q", answer="abstained text", status="success",
                        tool_calls=[{"tool_name": "t", "arguments": {}, "result": "[[1]]"}],
                        initial_data={"x": 1}, verification={"outcome": "reject"}, original_answer="2")
    rec = r.trajectory_record()
    assert rec["answer"] == "2" and rec["initial_data"] == {"x": 1} and rec["verification"]["outcome"] == "reject"
    save_trajectory_log([r], tmp_path)
    assert read_trajectories(tmp_path / "d_trajectory.json")["u"]["tool_calls"][0]["result"] == "[[1]]"


def test_manifest_b1_block():
    from capstone.run.manifest import b1_manifest

    shipped = str(Path(__file__).resolve().parents[1] / "run" / "configs" / "b1_verifier.json")
    m = b1_manifest(shipped, {"JUDGE_MODEL": "judge-x", "JUDGE_ENDPOINT": "http://j"})
    assert m["judge_model_resolved"] == "judge-x" and m["judge_endpoint_resolved"] == "http://j"
    assert m["config_sha256"] == VerifierConfig().sha256() and m["judge_prompt_sha256"]
    assert "API_KEY" not in json.dumps({k: v for k, v in m.items() if k != "verifier"})


def test_variants():
    from capstone.variants import build_post_answer_step

    assert build_post_answer_step("B0") is None
    with pytest.raises(NotImplementedError):
        build_post_answer_step("B2")
    with pytest.raises(ValueError):
        build_post_answer_step("B9")


def test_tracing_record_verification_is_noop_without_tracer():
    from capstone.observability.tracing import TaskSpan

    TaskSpan().record_verification({"outcome": "accept", "b1_path": "deterministic"})


# -- CLI ----------------------------------------------------------------------

def test_cli_replay_eval_gold_check(run_a, tool_outputs, gt_root, gold_sample, tmp_path, capsys):
    out = tmp_path / "cli_replay"
    cfg = tmp_path / "v.json"
    cfg.write_text(NO_JUDGE.model_dump_json())
    assert b1_main(["replay", str(run_a), str(out), "--tool-outputs", str(tool_outputs),
                    "--verifier-config", str(cfg)]) == 0
    assert b1_main(["eval", str(out), "--gt-root", str(gt_root)]) == 0
    assert (out / "b1_eval" / "b1_eval.md").exists() and (out / "b1_eval" / "b1_eval_cells.csv").exists()
    assert b1_main(["gold-check", "--gt-root", str(gold_sample), "--verifier-config", str(cfg),
                    "--out", str(tmp_path / "gc")]) == 0
    payload = json.loads((tmp_path / "gc" / "gold_check.json").read_text())
    assert payload["judge"] is False and payload["rows"]

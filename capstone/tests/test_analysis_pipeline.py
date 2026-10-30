import csv

import pytest

from capstone.analysis import labels as L
from capstone.analysis.cli import main
from capstone.analysis.compare import compare_runs
from capstone.analysis.loader import load_run, read_uuid_list
from capstone.analysis.metrics import accuracy_table, cost_table


def _row(rows, cap):
    return next(r for r in rows if r.capability == cap)


def test_load_run_merges_predictions_eval_gt_and_spans(run_a, gt_root):
    run = load_run(run_a, gt_root)
    assert run.run_id == "A" and run.variant == "B0" and run.has_spans
    items = run.by_key()
    assert len(items) == 6  # 4 hockey + 2 address (v2 missing prediction)
    u1 = items[(2, "u1")]
    assert u1.scored and u1.score == 1.0 and u1.has_prediction
    assert (
        u1.prompt_tokens,
        u1.completion_tokens,
        u1.total_tokens,
        u1.n_llm_calls,
    ) == (250, 50, 300, 2)
    assert u1.tool_outputs == ['[["42"]]']
    assert u1.gt_calls[0].name == "get_goals"
    v2 = items[(1, "v2")]
    assert not v2.scored and not v2.has_prediction


def test_accuracy_uses_scored_denominator(run_a, gt_root):
    run = load_run(run_a, gt_root)
    caps = accuracy_table(run, by="capability")
    cap1, cap2 = _row(caps, 1), _row(caps, 2)
    assert (cap1.n_items, cap1.n_scored, cap1.accuracy, cap1.coverage) == (
        2,
        1,
        1.0,
        0.5,
    )
    assert (cap2.n_scored, cap2.n_correct, cap2.accuracy) == (4, 1, 0.25)
    overall = accuracy_table(run, by="overall")[0]
    assert overall.n_scored == 5 and overall.accuracy == pytest.approx(2 / 5)
    doms = accuracy_table(run, by="domain")
    assert {(r.capability, r.domain) for r in doms} == {(1, "address"), (2, "hockey")}


def test_accuracy_excludes_reference_wrong(run_a, gt_root):
    run = load_run(run_a, gt_root)
    cap2 = _row(accuracy_table(run, by="capability", excluded={"u4"}), 2)
    assert (cap2.n_scored, cap2.n_excluded, cap2.accuracy) == (
        3,
        1,
        pytest.approx(1 / 3),
    )


def test_cost_table(run_a, gt_root):
    rows = cost_table(load_run(run_a, gt_root), price_in_per_m=1.0, price_out_per_m=2.0)
    cap2 = _row(rows, 2)
    assert (
        cap2.n == 4
        and cap2.latency_p50_s == pytest.approx(5.0)
        and cap2.latency_max_s == 300.0
    )
    assert cap2.n_with_tokens == 1 and cap2.total_tokens_sum == 300
    assert cap2.est_cost_usd == pytest.approx(250 / 1e6 + 50 * 2 / 1e6)


def test_auto_labels(run_a, gt_root):
    items = load_run(run_a, gt_root).by_key()
    lab = {u: L.auto_label(items[(2, u)]) for u in ("u2", "u3", "u4")}
    assert (lab["u2"].headline, lab["u2"].subreason) == (
        L.SUPPORTED_BUT_WRONG,
        "wrong_tool",
    )
    assert (lab["u3"].headline, lab["u3"].subreason) == (
        L.NOT_SUPPORTED,
        "answer_not_in_output",
    )
    assert (lab["u4"].headline, lab["u4"].subreason) == (L.NOT_SUPPORTED, "no_answer")
    ref = L.auto_label(items[(2, "u2")], reference_wrong={"u2"})
    assert ref.subreason == "reference_wrong" and ref.confidence == "high"


def test_auto_label_groundedness_and_policy(run_a, gt_root):
    item = load_run(run_a, gt_root).by_key()[(2, "u1")]
    item.turn_meta = {"groundedness_score": 0.0}
    assert L.auto_label(item).subreason == "answer_not_in_output"
    item.turn_meta = {"policy_adherance_score": 0}
    assert L.auto_label(item).subreason == "policy_violation"


def test_compare_calls_normalizes_arguments():
    from capstone.analysis.loader import ToolCall

    gt = [ToolCall("f", {"x": "Bruins", "n": 3})]
    assert L.compare_calls([ToolCall("f", {"x": " bruins", "n": "3"})], gt) == "match"
    assert (
        L.compare_calls([ToolCall("f", {"x": "Leafs", "n": 3})], gt)
        == "wrong_arguments"
    )
    assert L.compare_calls([ToolCall("g", {})], gt) == "wrong_tool"
    assert L.compare_calls([], []) == "no_gt"


def test_support_ratio():
    assert L.support_ratio("42", ['[["42"]]']) == 1.0
    assert L.support_ratio(
        "The answer is 1,234.0 goals", ["total 1234"]
    ) == pytest.approx(0.5)
    assert L.support_ratio("", ["x"]) is None
    assert L.support_ratio("42", []) is None


def test_compare_runs(run_a, run_b, gt_root):
    a, b = load_run(run_a, gt_root), load_run(run_b, gt_root)
    rows, pairs = compare_runs(a, b, n_resamples=500)
    assert len(pairs) == 5
    overall = next(r for r in rows if r.capability == "all")
    assert (overall.mcnemar.b, overall.mcnemar.c) == (0, 2)
    assert overall.bootstrap.mean_diff == pytest.approx(2 / 5)
    _rows_ex, pairs_ex = compare_runs(a, b, excluded={"u2"}, n_resamples=100)
    assert len(pairs_ex) == 4


def test_read_uuid_list(tmp_path):
    p = tmp_path / "ref_wrong.txt"
    p.write_text("# known bad references\nuuid,reason\nu1, wrong year\n\nu2  # typo\n")
    assert read_uuid_list(p) == {"u1", "u2"}
    assert read_uuid_list(None) == set()


def test_human_labels_override_and_validate(tmp_path):
    p = tmp_path / "labels.csv"
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=L.LABEL_FIELDS)
        w.writeheader()
        w.writerow(
            {"capability": 2, "uuid": "u2", "human_subreason": "wrong_arguments"}
        )
        w.writerow({"capability": 2, "uuid": "u3", "human_headline": ""})
    labels = L.read_human_labels(p)
    assert set(labels) == {(2, "u2")}
    assert (
        labels[(2, "u2")].headline == L.SUPPORTED_BUT_WRONG
        and labels[(2, "u2")].source == "human"
    )

    with p.open("a", newline="") as fh:
        csv.DictWriter(fh, fieldnames=L.LABEL_FIELDS).writerow(
            {
                "capability": 2,
                "uuid": "u4",
                "human_headline": "not_supported",
                "human_subreason": "wrong_tool",
            }
        )
    with pytest.raises(ValueError):
        L.read_human_labels(p)


def test_cli_summarize_compare_trace(run_a, run_b, gt_root, tmp_path):
    out = tmp_path / "out"
    excl = tmp_path / "ref_wrong.txt"
    excl.write_text("u4\n")
    assert (
        main(
            [
                "summarize",
                str(run_a),
                str(run_b),
                "--gt-root",
                str(gt_root),
                "--out",
                str(out),
                "--exclude-uuids",
                str(excl),
            ]
        )
        == 0
    )
    for name in (
        "accuracy_by_capability.csv",
        "accuracy_by_domain.csv",
        "cost_latency.csv",
        "error_labels.csv",
        "error_summary.csv",
        "report.md",
        "accuracy_by_capability.png",
        "error_breakdown.png",
        "latency.png",
    ):
        assert (out / name).exists(), name
    with (out / "error_labels.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    assert {(r["run_id"], r["uuid"]) for r in rows} == {
        ("A", "u2"),
        ("A", "u3"),
        ("A", "u4"),
        ("B", "u4"),
    }
    assert "Accuracy by capability" in (out / "report.md").read_text()

    # Feed human labels back in.
    rows[0]["human_subreason"] = "wrong_arguments"
    with (out / "error_labels.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=L.LABEL_FIELDS)
        w.writeheader()
        w.writerows(rows)
    assert (
        main(
            [
                "summarize",
                str(run_a),
                "--gt-root",
                str(gt_root),
                "--out",
                str(out / "relabeled"),
                "--labels",
                str(out / "error_labels.csv"),
                "--no-plots",
            ]
        )
        == 0
    )
    summary = (out / "relabeled" / "error_summary.csv").read_text()
    assert "wrong_arguments" in summary

    cmp_out = tmp_path / "cmp"
    assert (
        main(
            [
                "compare",
                str(run_a),
                str(run_b),
                "--gt-root",
                str(gt_root),
                "--out",
                str(cmp_out),
                "--resamples",
                "200",
            ]
        )
        == 0
    )
    assert (cmp_out / "comparison.csv").exists() and (
        cmp_out / "comparison.png"
    ).exists()
    assert "McNemar" in (cmp_out / "comparison.md").read_text()

    tr_out = tmp_path / "trace"
    assert (
        main(["trace", str(run_a), "--gt-root", str(gt_root), "--out", str(tr_out)])
        == 0
    )
    traces = list(tr_out.glob("example_trace_*.md"))
    assert len(traces) == 1 and "Agent answer" in traces[0].read_text()
    assert (
        main(
            [
                "trace",
                str(run_a),
                "--uuid",
                "u1",
                "--gt-root",
                str(gt_root),
                "--out",
                str(tr_out),
            ]
        )
        == 0
    )
    text = (tr_out / "example_trace_cap2_u1.md").read_text()
    assert "get_goals" in text and '-> [["42"]]' in text and "tokens:** 300" in text


def test_missing_gt_root_degrades(run_a, tmp_path):
    out = tmp_path / "out"
    assert (
        main(
            [
                "summarize",
                str(run_a),
                "--gt-root",
                str(tmp_path / "nope"),
                "--out",
                str(out),
                "--no-plots",
            ]
        )
        == 0
    )
    assert (out / "report.md").exists()

import json

from capstone.run import merge_eval


def _part(path, domain, n_gt, uuids_missing, scores):
    path.write_text(json.dumps({
        "capability_name": "c", "groundtruth_dir": "g", "prediction_dir": "p",
        "domains": {domain: {
            "domain": domain, "n_groundtruth": n_gt, "n_prediction": n_gt - len(uuids_missing),
            "n_paired": len(scores), "missing_prediction_uuids": uuids_missing,
            "extra_prediction_uuids": [], "dialogues": [{"score": s} for s in scores],
            "summary": {"num_samples": n_gt},
        }},
        "summary": {},
    }))


def test_merge_fails_on_domain_without_predictions(tmp_path, capsys):
    parts = tmp_path / "parts"
    parts.mkdir()
    _part(parts / "a.json", "a", 2, [], [1.0, 0.0])
    _part(parts / "b.json", "b", 2, ["u1", "u2"], [])
    out = tmp_path / "cap2.json"
    assert merge_eval.main(["--parts", str(parts), "--out", str(out)]) == 2
    assert "MISSING predictions: b: 2" in capsys.readouterr().err
    assert json.loads(out.read_text())["summary"]["n_missing_predictions"] == 2
    assert merge_eval.main(["--parts", str(parts), "--out", str(out), "--allow-missing"]) == 0


def test_merge_complete_parts_exit_zero(tmp_path):
    parts = tmp_path / "parts"
    parts.mkdir()
    _part(parts / "a.json", "a", 2, [], [1.0, 0.0])
    out = tmp_path / "cap2.json"
    assert merge_eval.main(["--parts", str(parts), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["summary"]["mean_dialogue_score"] == 0.5

import json
import subprocess

from capstone.run import manifest as M


def test_redact_argv():
    argv = [
        "vllm",
        "serve",
        "openai/gpt-oss-120b",
        "--api-key",
        "s3cr3t",
        "--hf-token=abc",
        "--tensor-parallel-size",
        "1",
    ]
    out = M.redact_argv(argv)
    assert "s3cr3t" not in out and "--hf-token=abc" not in out
    assert out[3:6] == ["--api-key", "<redacted>", "--hf-token=<redacted>"]
    assert out[-2:] == ["--tensor-parallel-size", "1"]


def test_parse_reasoning_effort():
    assert M.parse_reasoning_effort('{"reasoning_effort": "high"}') == "high"
    assert M.parse_reasoning_effort('{"reasoning": {"effort": "low"}}') == "low"
    assert M.parse_reasoning_effort("not json") is None
    assert M.parse_reasoning_effort(None) is None


def test_local_vllm_cmdline(tmp_path):
    proc = tmp_path / "proc"
    (proc / "12").mkdir(parents=True)
    (proc / "12" / "cmdline").write_bytes(
        b"python\0-m\0vllm.entrypoints.openai.api_server\0--api-key\0k\0"
    )
    (proc / "self").mkdir()
    assert M.local_vllm_cmdline(proc) == [
        "python",
        "-m",
        "vllm.entrypoints.openai.api_server",
        "--api-key",
        "<redacted>",
    ]
    assert M.local_vllm_cmdline(tmp_path / "missing") is None


def test_start_mark_finish_roundtrip(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
        ],
        cwd=repo,
        check=True,
    )
    run = tmp_path / "runs" / "b0_test"
    env = {
        "LITELLM_EXTRA_BODY": '{"reasoning_effort": "medium"}',
        "JUDGE_ENDPOINT": "http://localhost:8000",
        "LITELLM_API_KEY": "must-not-leak",
        "AGENT_TIMEOUT_SECONDS": "300",
    }
    args = M._parser().parse_args(
        [
            "start",
            "--run-dir",
            str(run),
            "--model",
            "gpt-oss-120b",
            "--temperature",
            "0",
            "--n",
            "2",
            "--shards",
            "8",
            "--capabilities",
            "1",
            "2",
            "--repo",
            str(repo),
            "--no-probe",
        ]
    )
    M.write_manifest(run, M.build_start_manifest(args, env=env))
    data = json.loads((run / "config.json").read_text())
    assert data["run_id"] == "b0_test" and data["agent_variant"] == "B0"
    assert data["reasoning_effort"] == "medium" and data["max_samples_per_domain"] == 2
    assert (
        data["agent_timeout_s"] == 300.0
        and data["judge"]["endpoint"] == "http://localhost:8000"
    )
    assert len(data["git"]["sha"]) == 40 and data["git"]["dirty"] is False
    assert "must-not-leak" not in (run / "config.json").read_text()

    assert (
        M.main(
            [
                "mark",
                "--run-dir",
                str(run),
                "--event",
                "agents_finished",
                "--exit-code",
                "0",
            ]
        )
        == 0
    )
    M.finish(run)
    data = json.loads((run / "config.json").read_text())
    assert data["status"] == "ok" and data["wall_clock_s"] >= 0
    assert [e["event"] for e in data["events"]] == ["agents_finished", "finished_at"]
    assert data["events"][0]["exit_code"] == 0


def test_vllm_info_unreachable():
    info = M.vllm_info("http://127.0.0.1:9/v1")
    assert info["reachable"] is False and info["version"] is None

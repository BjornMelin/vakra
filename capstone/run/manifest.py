"""Write and update the run manifest ``$RUN/config.json``.

The manifest records everything needed to reproduce or compare a run: model,
serving stack, sampling settings, code version, sharding, judge settings and
phase timestamps. It never records secrets: environment variables are read
from an explicit allow-list and command-line flags that look like credentials
are redacted.

Usage::

    python -m capstone.run.manifest start  --run-dir RUN --variant B0 --model gpt-oss-120b ...
    python -m capstone.run.manifest mark   --run-dir RUN --event agents_finished [--status ok]
    python -m capstone.run.manifest finish --run-dir RUN [--status ok]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from importlib import metadata
from pathlib import Path
from typing import Any

from capstone.trajectories import is_sidecar

MANIFEST_NAME = "config.json"
SCHEMA_VERSION = 1

#: Non-secret environment variables worth recording.
ENV_ALLOWLIST = (
    "LITELLM_BASE_URL",
    "LITELLM_EXTRA_BODY",
    "AGENT_TIMEOUT_SECONDS",
    "JUDGE_BACKEND",
    "JUDGE_ENDPOINT",
    "JUDGE_MODEL",
    "VAKRA_TRACING",
    "VAKRA_LOG_LEVEL",
    "VAKRA_RUN_ID",
    "VAKRA_AGENT_VARIANT",
    "VAKRA_TRACE_DIR",
    "PHOENIX_COLLECTOR_ENDPOINT",
    "PHOENIX_PROJECT_NAME",
)

#: Packages whose versions affect results or tracing.
PACKAGES = (
    "mcp",
    "langchain-core",
    "langgraph",
    "langchain-litellm",
    "litellm",
    "langchain-openai",
    "vllm",
    "arize-phoenix-otel",
    "openinference-instrumentation-langchain",
    "opentelemetry-sdk",
)

_SECRET_FLAG = re.compile(
    r"(key|token|secret|password|passwd|credential)", re.IGNORECASE
)


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def redact_argv(argv: list[str]) -> list[str]:
    """Redact values of credential-like flags (``--api-key X`` and ``--api-key=X``)."""
    out: list[str] = []
    redact_next = False
    for arg in argv:
        if redact_next:
            out.append("<redacted>")
            redact_next = False
            continue
        if arg.startswith("-") and _SECRET_FLAG.search(arg):
            if "=" in arg:
                out.append(arg.split("=", 1)[0] + "=<redacted>")
            else:
                out.append(arg)
                redact_next = True
            continue
        out.append(arg)
    return out


def parse_reasoning_effort(extra_body: str | None) -> str | None:
    if not extra_body:
        return None
    try:
        body = json.loads(extra_body)
    except json.JSONDecodeError:
        return None
    if not isinstance(body, dict):
        return None
    effort = body.get("reasoning_effort")
    if effort is None and isinstance(body.get("reasoning"), dict):
        effort = body["reasoning"].get("effort")
    return effort


def _run(cmd: list[str], cwd: Path | None = None) -> str | None:
    try:
        return subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def git_info(repo: Path) -> dict[str, Any]:
    status = _run(["git", "status", "--porcelain", "--untracked-files=no"], repo)
    return {
        "sha": _run(["git", "rev-parse", "HEAD"], repo),
        "short_sha": _run(["git", "rev-parse", "--short", "HEAD"], repo),
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo),
        "dirty": bool(status) if status is not None else None,
        "dirty_files": status.splitlines() if status else [],
    }


def package_versions(names: tuple[str, ...] = PACKAGES) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _get_json(url: str, timeout: float = 5.0) -> Any:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def vllm_info(base_url: str | None) -> dict[str, Any]:
    """Query a vLLM OpenAI-compatible server for its version and served models."""
    if not base_url:
        return {}
    root = base_url.rstrip("/")
    root = root.removesuffix("/v1")
    version = _get_json(f"{root}/version")
    models = _get_json(f"{root}/v1/models")
    served = []
    if isinstance(models, dict):
        for m in models.get("data", []):
            served.append(
                {k: m.get(k) for k in ("id", "root", "max_model_len") if k in m}
            )
    return {
        "base_url": base_url,
        "version": version.get("version") if isinstance(version, dict) else None,
        "served_models": served,
        "reachable": models is not None,
    }


def local_vllm_cmdline(proc_root: Path = Path("/proc")) -> list[str] | None:
    """Return the redacted command line of a local ``vllm serve`` process, if any."""
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            argv = [
                a
                for a in (entry / "cmdline")
                .read_bytes()
                .decode(errors="replace")
                .split("\0")
                if a
            ]
        except OSError:
            continue
        joined = " ".join(argv)
        if "vllm" in joined and (
            " serve " in f" {joined} " or "vllm.entrypoints" in joined
        ):
            return redact_argv(argv)
    return None


def read_manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / MANIFEST_NAME
    return json.loads(path.read_text()) if path.exists() else {}


def write_manifest(run_dir: Path, manifest: dict[str, Any]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / MANIFEST_NAME
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=False) + "\n")
    tmp.replace(path)
    return path


def build_start_manifest(
    args: argparse.Namespace, env: dict[str, str] | None = None
) -> dict[str, Any]:
    env = dict(os.environ if env is None else env)
    repo = Path(args.repo).resolve()
    extra_body = env.get("LITELLM_EXTRA_BODY")
    base_url = args.base_url or env.get("LITELLM_BASE_URL")
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": args.run_id or Path(args.run_dir).name,
        "agent_variant": args.variant,
        "split": args.split,
        "model": args.model,
        "provider": args.provider,
        "temperature": args.temperature,
        "reasoning_effort": args.reasoning_effort or parse_reasoning_effort(extra_body),
        "litellm_extra_body": json.loads(extra_body) if extra_body else None,
        "max_samples_per_domain": args.n,
        "shards": args.shards,
        "parallel_jobs": getattr(args, "parallel", None),
        "eval_jobs": getattr(args, "eval_jobs", None),
        "tasks_planned": json.loads(args.task_counts)
        if getattr(args, "task_counts", None)
        else None,
        "capabilities": args.capabilities,
        "shard_timeout_s": args.shard_timeout,
        "agent_timeout_s": float(env["AGENT_TIMEOUT_SECONDS"])
        if env.get("AGENT_TIMEOUT_SECONDS")
        else None,
        "runner_args": args.runner_args,
        "b1": b1_manifest(getattr(args, "verifier_config", None), env)
        if args.variant != "B0"
        else None,
        "judge": {
            "backend": env.get("JUDGE_BACKEND"),
            "endpoint": env.get("JUDGE_ENDPOINT"),
            "model": env.get("JUDGE_MODEL"),
        },
        "eval_parallel": args.eval_parallel,
        "config_file": args.config_file,
        "vllm": {
            **({} if args.no_probe else vllm_info(base_url)),
            "serve_cmdline": None if args.no_probe else local_vllm_cmdline(),
            "serve_flags": args.vllm_flags,
        },
        "git": git_info(repo),
        "packages": package_versions(),
        "python": sys.version.split()[0],
        "host": {"hostname": socket.gethostname(), "platform": platform.platform()},
        "env": {k: env[k] for k in ENV_ALLOWLIST if k in env},
        "timestamps": {"started_at": utc_now()},
        "events": [],
        "status": "running",
    }


def b1_manifest(verifier_config: str | None, env: dict[str, str]) -> dict[str, Any]:
    """Resolved B1 verifier config, its hash and the judge prompt hash (WS2.2)."""
    from capstone.b1.config import VerifierConfig
    from capstone.b1.step import describe_config

    cfg = VerifierConfig.load(verifier_config)
    out = describe_config(cfg)
    out["config_file"] = verifier_config
    judge = out["verifier"]["judge"]
    out["judge_model_resolved"] = judge["model"] or env.get("JUDGE_MODEL")
    out["judge_endpoint_resolved"] = judge["endpoint"] or env.get("JUDGE_ENDPOINT")
    return out


def mark(
    run_dir: Path, event: str, status: str | None = None, **extra: Any
) -> dict[str, Any]:
    manifest = read_manifest(run_dir)
    now = utc_now()
    manifest.setdefault("timestamps", {})[event] = now
    record = {"event": event, "at": now}
    if status is not None:
        record["status"] = status
    record.update({k: v for k, v in extra.items() if v is not None})
    manifest.setdefault("events", []).append(record)
    write_manifest(run_dir, manifest)
    return manifest


def finish(run_dir: Path, status: str = "ok") -> dict[str, Any]:
    manifest = mark(run_dir, "finished_at", status=status)
    started = manifest.get("timestamps", {}).get("started_at")
    if started:
        elapsed = dt.datetime.fromisoformat(
            manifest["timestamps"]["finished_at"]
        ) - dt.datetime.fromisoformat(started)
        manifest["wall_clock_s"] = elapsed.total_seconds()
    manifest["status"] = status
    manifest["predictions"] = count_predictions(Path(run_dir))
    write_manifest(run_dir, manifest)
    return manifest


def count_predictions(run_dir: Path) -> dict[str, int]:
    """Count agent prediction records per capability directory (cap<C>/)."""
    counts: dict[str, int] = {}
    for cap_dir in sorted(run_dir.glob("cap[0-9]*")):
        if not cap_dir.is_dir():
            continue
        n = 0
        for path in cap_dir.glob("*.json"):
            if is_sidecar(path):
                continue
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(data, list):
                n += len(data)
        counts[cap_dir.name] = n
    return counts


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m capstone.run.manifest", description=__doc__.split("\n\n")[0]
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start", help="create $RUN/config.json")
    s.add_argument("--run-dir", required=True)
    s.add_argument("--run-id")
    s.add_argument("--variant", default="B0")
    s.add_argument("--split", default="train")
    s.add_argument("--model", required=True)
    s.add_argument("--provider", default="litellm")
    s.add_argument("--base-url", help="defaults to $LITELLM_BASE_URL")
    s.add_argument("--temperature", type=float)
    s.add_argument("--reasoning-effort")
    s.add_argument("--n", type=int, help="--max-samples-per-domain")
    s.add_argument("--shards", type=int)
    s.add_argument(
        "--parallel", type=int, help="global agent job slots (queue mode)"
    )
    s.add_argument(
        "--eval-jobs", type=int, help="per-domain evaluator slots (0 = per capability)"
    )
    s.add_argument(
        "--task-counts", help='JSON {"<cap>": <tasks selected>} for this run'
    )
    s.add_argument("--capabilities", type=int, nargs="*", default=[])
    s.add_argument("--shard-timeout", type=float)
    s.add_argument(
        "--runner-args", default="", help="extra benchmark_runner.py args, verbatim"
    )
    s.add_argument("--eval-parallel", action="store_true")
    s.add_argument("--config-file")
    s.add_argument("--verifier-config", help="B1 verifier config JSON (variant B1+)")
    s.add_argument(
        "--vllm-flags", help="vLLM serve flags as configured (informational)"
    )
    s.add_argument("--repo", default=".")
    s.add_argument(
        "--no-probe", action="store_true", help="skip vLLM HTTP and /proc probes"
    )

    m = sub.add_parser("mark", help="record a phase event")
    m.add_argument("--run-dir", required=True)
    m.add_argument("--event", required=True)
    m.add_argument("--status")
    m.add_argument("--exit-code", type=int)

    f = sub.add_parser("finish", help="record completion and wall-clock time")
    f.add_argument("--run-dir", required=True)
    f.add_argument("--status", default="ok")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    run_dir = Path(args.run_dir)
    if args.cmd == "start":
        path = write_manifest(run_dir, build_start_manifest(args))
        print(f"manifest: {path}")
    elif args.cmd == "mark":
        mark(run_dir, args.event, status=args.status, exit_code=args.exit_code)
    else:
        finish(run_dir, status=args.status)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

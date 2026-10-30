"""Tests for capstone.observability.tracing (no Phoenix server required)."""

from __future__ import annotations

import asyncio
import json

import pytest

from capstone.observability import tracing

pytest.importorskip("opentelemetry.sdk")
pytest.importorskip("openinference.instrumentation.langchain")


def test_config_from_env_defaults_disabled():
    cfg = tracing.TracingConfig.from_env({})
    assert cfg.enabled is False
    assert cfg.traces_url == "http://127.0.0.1:6006/v1/traces"
    assert cfg.variant == "B0"


def test_config_from_env_parses_values(tmp_path):
    cfg = tracing.TracingConfig.from_env(
        {
            "VAKRA_TRACING": "yes",
            "PHOENIX_COLLECTOR_ENDPOINT": "none",
            "VAKRA_RUN_ID": "b0_2210",
            "VAKRA_AGENT_VARIANT": "B2",
            "VAKRA_TRACE_DIR": str(tmp_path),
        }
    )
    assert cfg.enabled and cfg.traces_url is None
    assert (cfg.run_id, cfg.variant, cfg.trace_dir) == ("b0_2210", "B2", tmp_path)


def test_disabled_is_noop():
    assert tracing.setup_tracing(tracing.TracingConfig(enabled=False)) is False
    assert not tracing.is_enabled()
    with tracing.task_span(capability_id=2, domain="hockey", uuid="u1") as span:
        span.record_result(status="success", answer="x", n_tool_calls=0)
    tracing.shutdown_tracing()  # safe when never enabled


def _read_spans(trace_dir):
    records = []
    for path in trace_dir.glob("spans-*.jsonl"):
        records += [json.loads(line) for line in path.read_text().splitlines()]
    return records


def test_enabled_tags_llm_and_tool_spans(tmp_path):
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.tools import StructuredTool

    cfg = tracing.TracingConfig(
        enabled=True, endpoint=None, run_id="run-test", variant="B1", trace_dir=tmp_path
    )
    assert tracing.setup_tracing(cfg) is True
    try:
        llm = GenericFakeChatModel(
            messages=iter(
                [
                    AIMessage(
                        content="42",
                        usage_metadata={
                            "input_tokens": 11,
                            "output_tokens": 3,
                            "total_tokens": 14,
                        },
                    )
                ]
            )
        )

        async def lookup(team: str) -> str:
            return f"{team}: 42 goals"

        tool = StructuredTool.from_function(
            coroutine=lookup, name="get_goals", description="d"
        )

        async def run_item():
            # Mirrors benchmark_runner: agent work happens in a child asyncio task.
            async def agent():
                await tool.ainvoke({"team": "Bruins"})
                return await llm.ainvoke("how many goals?")

            return await asyncio.wait_for(agent(), timeout=5)

        with tracing.task_span(
            capability_id=2, domain="hockey", uuid="u-1", query="q"
        ) as span:
            msg = asyncio.run(run_item())
            span.record_result(
                status="success", answer=msg.content, n_tool_calls=1, duration_s=0.1
            )
    finally:
        tracing.shutdown_tracing()

    spans = _read_spans(tmp_path)
    by_kind = {s.get("openinference.span.kind"): s for s in spans}
    assert {"CHAIN", "LLM", "TOOL"} <= set(by_kind)
    for s in spans:
        assert s["vakra.run_id"] == "run-test"
        assert s["vakra.variant"] == "B1"
        assert s["vakra.uuid"] == "u-1"
        assert s["vakra.domain"] == "hockey"
        assert s["vakra.capability_id"] == 2
        assert s["latency_ms"] is not None
    assert by_kind["TOOL"]["tool.name"] == "get_goals"
    assert by_kind["LLM"]["llm.token_count.total"] == 14
    root = next(s for s in spans if s["name"] == "vakra.task")
    assert root["parent_id"] is None
    assert root["vakra.status"] == "success" and root["output.value"] == "42"
    assert not tracing.is_enabled()

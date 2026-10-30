"""OpenTelemetry SDK pieces used by ``capstone.observability.tracing``.

Imported lazily, only when tracing is enabled, so the OpenTelemetry SDK stays
an optional dependency of the benchmark runner.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from opentelemetry.context import Context
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from capstone.observability.tracing import (
    ATTR_CAPABILITY,
    ATTR_DOMAIN,
    ATTR_N_TOOL_CALLS,
    ATTR_RUN_ID,
    ATTR_STATUS,
    ATTR_UUID,
    ATTR_VARIANT,
    OI_INPUT_VALUE,
    OI_OUTPUT_VALUE,
    OI_SPAN_KIND,
)


class TaskAttributesSpanProcessor(SpanProcessor):
    """Copies the current task's attributes onto every span when it starts.

    The attributes live in a ContextVar set by ``task_span()``. asyncio tasks
    and LangChain's executor hops copy the context, so LLM and tool spans
    created deep inside the agent inherit the task's run/variant/uuid tags.
    """

    def __init__(self, attributes_var: ContextVar[Mapping[str, Any] | None]):
        self._attributes_var = attributes_var

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:
        attrs = self._attributes_var.get()
        if attrs:
            span.set_attributes(dict(attrs))


_JSONL_ATTRS = (
    ATTR_RUN_ID,
    ATTR_VARIANT,
    ATTR_CAPABILITY,
    ATTR_DOMAIN,
    ATTR_UUID,
    ATTR_STATUS,
    ATTR_N_TOOL_CALLS,
    OI_SPAN_KIND,
    "llm.model_name",
    "llm.token_count.prompt",
    "llm.token_count.completion",
    "llm.token_count.total",
    "tool.name",
)


class JsonlSpanExporter(SpanExporter):
    """Writes one compact JSON object per finished span (append-only)."""

    def __init__(self, path: Path, max_chars: int = 4000):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_chars = max_chars
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        lines = [
            json.dumps(span_to_record(s, self._max_chars), default=str) for s in spans
        ]
        with self._lock, self._path.open("a", encoding="utf-8") as fh:
            fh.write("".join(line + "\n" for line in lines))
        return SpanExportResult.SUCCESS


def span_to_record(span: ReadableSpan, max_chars: int = 4000) -> dict[str, Any]:
    """Compact, analysis-friendly view of a ReadableSpan."""
    attrs = dict(span.attributes or {})
    ctx = span.get_span_context()
    record: dict[str, Any] = {
        "trace_id": format(ctx.trace_id, "032x"),
        "span_id": format(ctx.span_id, "016x"),
        "parent_id": format(span.parent.span_id, "016x") if span.parent else None,
        "name": span.name,
        "start_ns": span.start_time,
        "end_ns": span.end_time,
        "latency_ms": (span.end_time - span.start_time) / 1e6
        if span.end_time and span.start_time
        else None,
        "status": span.status.status_code.name if span.status else None,
    }
    for key in _JSONL_ATTRS:
        if key in attrs:
            record[key] = attrs[key]
    for key in (OI_INPUT_VALUE, OI_OUTPUT_VALUE):
        if key in attrs:
            record[key] = str(attrs[key])[:max_chars]
    return record

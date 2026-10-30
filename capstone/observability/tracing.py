"""Opt-in OpenTelemetry tracing for VAKRA benchmark runs.

Disabled unless ``VAKRA_TRACING`` is truthy. When disabled every public
function is a cheap no-op and no OpenTelemetry/Phoenix package is imported,
so the benchmark runner keeps working with only its upstream dependencies.

When enabled:

* LangChain/LangGraph are instrumented with the OpenInference LangChain
  instrumentor. That covers every LLM call made through ``ChatLiteLLM``
  (``--provider litellm``), including token counts and latency, the LangGraph
  ReAct loop, and every MCP tool call, because the agent invokes MCP tools
  through LangChain ``StructuredTool`` wrappers (``agents/mcp_tool_wrapper.py``).
* ``task_span()`` opens one root ``vakra.task`` span per benchmark item, and a
  span processor stamps ``vakra.*`` attributes (run id, agent variant,
  capability, domain, uuid) plus ``session.id`` onto every span started inside
  it, so LLM and tool spans can be filtered and grouped per task in Phoenix.
* Spans are exported over OTLP/HTTP to Phoenix (``PHOENIX_COLLECTOR_ENDPOINT``)
  and, if ``VAKRA_TRACE_DIR`` is set, also written as compact JSON lines to
  ``$VAKRA_TRACE_DIR/spans-<pid>.jsonl`` for offline analysis
  (``python -m capstone.analysis``).

Environment variables:
  VAKRA_TRACING               1/true/yes/on to enable (default: off)
  PHOENIX_COLLECTOR_ENDPOINT  Phoenix base URL (default http://127.0.0.1:6006);
                              set to "none" to skip OTLP export
  PHOENIX_PROJECT_NAME        Phoenix project (default vakra-capstone)
  VAKRA_RUN_ID                run identifier (default: unset)
  VAKRA_AGENT_VARIANT         B0 / B1 / B2 (default B0)
  VAKRA_TRACE_DIR             directory for local JSONL span copies (optional)
  VAKRA_TRACE_MAX_CHARS       truncate input/output values in JSONL (default 4000)
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}
DEFAULT_ENDPOINT = "http://127.0.0.1:6006"
DEFAULT_PROJECT = "vakra-capstone"

# Attribute keys. "vakra.*" are ours; the rest are OpenInference conventions.
ATTR_RUN_ID = "vakra.run_id"
ATTR_VARIANT = "vakra.variant"
ATTR_CAPABILITY = "vakra.capability_id"
ATTR_DOMAIN = "vakra.domain"
ATTR_UUID = "vakra.uuid"
ATTR_STATUS = "vakra.status"
ATTR_N_TOOL_CALLS = "vakra.n_tool_calls"
ATTR_DURATION_S = "vakra.duration_s"
ATTR_ERROR = "vakra.error"
ATTR_B1_OUTCOME = "vakra.b1.outcome"
ATTR_B1_PATH = "vakra.b1.path"
ATTR_B1_REASON = "vakra.b1.reason"
ATTR_B1_DURATION_S = "vakra.b1.duration_s"
ATTR_B1_ACTION = "vakra.b1.action"
OI_SESSION_ID = "session.id"
OI_SPAN_KIND = "openinference.span.kind"
OI_INPUT_VALUE = "input.value"
OI_OUTPUT_VALUE = "output.value"
OI_METADATA = "metadata"

# Attributes stamped onto every span started inside task_span().
_task_attributes: contextvars.ContextVar[Mapping[str, Any] | None] = (
    contextvars.ContextVar("vakra_task_attributes", default=None)
)


@dataclass(frozen=True)
class TracingConfig:
    enabled: bool = False
    endpoint: str | None = DEFAULT_ENDPOINT
    project_name: str = DEFAULT_PROJECT
    run_id: str | None = None
    variant: str = "B0"
    trace_dir: Path | None = None
    max_chars: int = 4000

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> TracingConfig:
        env = os.environ if env is None else env
        endpoint = env.get("PHOENIX_COLLECTOR_ENDPOINT", DEFAULT_ENDPOINT).strip()
        trace_dir = env.get("VAKRA_TRACE_DIR", "").strip()
        return cls(
            enabled=env.get("VAKRA_TRACING", "").strip().lower() in _TRUTHY,
            endpoint=None if endpoint.lower() in {"", "none", "off"} else endpoint,
            project_name=env.get("PHOENIX_PROJECT_NAME", DEFAULT_PROJECT),
            run_id=env.get("VAKRA_RUN_ID") or None,
            variant=env.get("VAKRA_AGENT_VARIANT", "B0"),
            trace_dir=Path(trace_dir) if trace_dir else None,
            max_chars=int(env.get("VAKRA_TRACE_MAX_CHARS", "4000")),
        )

    @property
    def traces_url(self) -> str | None:
        if self.endpoint is None:
            return None
        base = self.endpoint.rstrip("/")
        return base if base.endswith("/v1/traces") else base + "/v1/traces"


class _State:
    lock = threading.Lock()
    config: TracingConfig | None = None
    provider: Any = None
    tracer: Any = None


def is_enabled() -> bool:
    return _State.tracer is not None


def setup_tracing(config: TracingConfig | None = None) -> bool:
    """Configure tracing from ``config`` (default: environment). Idempotent.

    Returns True if tracing is active. Returns False (and logs why) when
    disabled or when the optional packages are missing; never raises for
    those cases so a run is never blocked by observability.
    """
    config = config or TracingConfig.from_env()
    with _State.lock:
        if _State.tracer is not None:
            return True
        if not config.enabled:
            return False
        try:
            from openinference.instrumentation.langchain import LangChainInstrumentor
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            from capstone.observability.exporters import (
                JsonlSpanExporter,
                TaskAttributesSpanProcessor,
            )
        except ImportError as exc:
            logger.warning(
                "VAKRA_TRACING is set but tracing packages are missing (%s). "
                "Install with: uv pip install -r capstone/requirements.txt. "
                "Continuing without tracing.",
                exc,
            )
            return False

        resource = Resource.create(
            {
                "service.name": "vakra-benchmark",
                # Phoenix routes spans to a project via this resource attribute.
                "openinference.project.name": config.project_name,
            }
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(TaskAttributesSpanProcessor(_task_attributes))
        if config.traces_url:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=config.traces_url))
            )
        if config.trace_dir is not None:
            path = config.trace_dir / f"spans-{os.getpid()}.jsonl"
            provider.add_span_processor(
                BatchSpanProcessor(JsonlSpanExporter(path, max_chars=config.max_chars))
            )

        LangChainInstrumentor().instrument(tracer_provider=provider)
        _State.config = config
        _State.provider = provider
        _State.tracer = provider.get_tracer("vakra.capstone")
        logger.info(
            "VAKRA tracing enabled: project=%s otlp=%s jsonl_dir=%s run_id=%s variant=%s",
            config.project_name,
            config.traces_url,
            config.trace_dir,
            config.run_id,
            config.variant,
        )
        return True


def shutdown_tracing() -> None:
    """Flush and shut down exporters. Safe to call when tracing is disabled."""
    with _State.lock:
        if _State.provider is None:
            return
        try:
            from openinference.instrumentation.langchain import LangChainInstrumentor

            LangChainInstrumentor().uninstrument()
        finally:
            _State.provider.shutdown()
            _State.provider = _State.tracer = _State.config = None


class TaskSpan:
    """Handle yielded by ``task_span``; records the outcome of one item."""

    def __init__(self, span: Any = None, max_chars: int = 4000):
        self._span = span
        self._max_chars = max_chars

    def record_result(
        self,
        *,
        status: str,
        answer: str | None = None,
        n_tool_calls: int | None = None,
        duration_s: float | None = None,
        error: str | None = None,
    ) -> None:
        if self._span is None:
            return
        from opentelemetry.trace import Status, StatusCode

        attrs: dict[str, Any] = {ATTR_STATUS: status}
        if answer is not None:
            attrs[OI_OUTPUT_VALUE] = answer[: self._max_chars]
        if n_tool_calls is not None:
            attrs[ATTR_N_TOOL_CALLS] = n_tool_calls
        if duration_s is not None:
            attrs[ATTR_DURATION_S] = duration_s
        if error:
            attrs[ATTR_ERROR] = error[: self._max_chars]
        self._span.set_attributes(attrs)
        self._span.set_status(
            Status(StatusCode.OK if status == "success" else StatusCode.ERROR)
        )

    def record_verification(self, verdict: dict[str, Any]) -> None:
        """B1 outcome on the task's root span (b1_path is logged per task)."""
        if self._span is None:
            return
        attrs = {
            ATTR_B1_OUTCOME: verdict.get("outcome"),
            ATTR_B1_PATH: verdict.get("b1_path"),
            ATTR_B1_REASON: verdict.get("reason"),
            ATTR_B1_DURATION_S: verdict.get("duration_s"),
            ATTR_B1_ACTION: verdict.get("action"),
        }
        self._span.set_attributes({k: v for k, v in attrs.items() if v is not None})


@contextmanager
def task_span(
    *,
    capability_id: int,
    domain: str,
    uuid: str,
    query: str | None = None,
) -> Iterator[TaskSpan]:
    """Root span for one benchmark item. A no-op when tracing is disabled."""
    if _State.tracer is None:
        yield TaskSpan()
        return
    config = _State.config
    assert config is not None
    attrs: dict[str, Any] = {
        ATTR_VARIANT: config.variant,
        ATTR_CAPABILITY: capability_id,
        ATTR_DOMAIN: domain,
        ATTR_UUID: uuid,
        OI_SESSION_ID: f"{config.run_id}:{uuid}" if config.run_id else uuid,
    }
    if config.run_id:
        attrs[ATTR_RUN_ID] = config.run_id
    token = _task_attributes.set(attrs)
    try:
        root_attrs = {
            OI_SPAN_KIND: "CHAIN",
            OI_METADATA: json.dumps(
                {
                    k.removeprefix("vakra."): v
                    for k, v in attrs.items()
                    if k.startswith("vakra.")
                }
            ),
        }
        if query is not None:
            root_attrs[OI_INPUT_VALUE] = query[: config.max_chars]
        with _State.tracer.start_as_current_span(
            "vakra.task", attributes=root_attrs
        ) as span:
            yield TaskSpan(span, max_chars=config.max_chars)
    finally:
        _task_attributes.reset(token)

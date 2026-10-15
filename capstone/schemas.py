"""VAKRA Capstone shared evidence / claim / trace schemas (draft for Oct 15 gate).

Bjorn owns freeze + commit; Thomas consumes the fixture.
Aligned to Execution Timeline v1.2 (IBM sales_in_weather first).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class UnitsMetric(str, Enum):
    """Canonical sales unit for RCA. Confirm with Thomas before freeze."""

    ITEM_UNITS_SOLD = "item_units_sold"


class PeriodWindow(BaseModel):
    """Inclusive calendar window in source timezone (document TZ with Thomas)."""

    start: str = Field(..., description="YYYY-MM-DD")
    end: str = Field(..., description="YYYY-MM-DD")
    store_id: str
    complete_daily_sales_coverage: Optional[bool] = None


class EvidenceSource(BaseModel):
    source_id: str = Field(..., description="Stable id for this evidence blob")
    kind: Literal[
        "sql_query",
        "tool_call",
        "pilot_report",
        "manual_note",
        "weather_join",
    ]
    table_or_tool: str
    query_or_args: dict[str, Any] = Field(default_factory=dict)
    revision: Optional[str] = Field(
        None, description="DB hash, HF revision, or tool version"
    )


class Evidence(BaseModel):
    """One grounded observation the agent may cite."""

    evidence_id: str
    source: EvidenceSource
    period: PeriodWindow
    units_metric: UnitsMetric = UnitsMetric.ITEM_UNITS_SOLD
    value: float | int | str | dict[str, Any]
    notes: Optional[str] = None


class ClaimKind(str, Enum):
    DESCRIPTIVE_DELTA = "descriptive_delta"
    ITEM_CONTRIBUTION = "item_contribution"
    COVERAGE = "coverage"
    WEATHER_ASSOCIATION = "weather_association"
    OTHER = "other"


class Claim(BaseModel):
    """Numerical or qualitative claim that must cite evidence IDs."""

    claim_id: str
    kind: ClaimKind
    text: str
    numeric_value: Optional[float] = None
    units_metric: Optional[UnitsMetric] = None
    evidence_ids: list[str] = Field(min_length=1)
    causal: bool = Field(
        False,
        description="True only for causal language; keep descriptive by default",
    )

    @field_validator("evidence_ids")
    @classmethod
    def non_empty_ids(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("claims must cite at least one evidence_id")
        return v


class ToolCallRecord(BaseModel):
    name: str
    arguments: dict[str, Any]
    status: Literal["ok", "error", "timeout"]
    result_summary: Optional[str] = None
    error: Optional[str] = None
    latency_ms: Optional[int] = None
    evidence_ids_produced: list[str] = Field(default_factory=list)


class Trace(BaseModel):
    """Full run log for one agent investigation."""

    trace_id: str
    model_id: str = Field(..., description="Pinned model identifier")
    prompt_version: str
    temperature: float
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    token_usage: Optional[dict[str, int]] = None
    status: Literal["success", "bounded_failure", "error"] = "success"
    error: Optional[str] = None


class SharedFixture(BaseModel):
    """Oct 15 exit artifact: one fixture both teammates can load."""

    schema_version: str = "0.1.0-draft"
    units_metric: UnitsMetric = UnitsMetric.ITEM_UNITS_SOLD
    model_id: Optional[str] = Field(
        None, description="Fill after smoke test; required to freeze"
    )
    example_trace: Trace

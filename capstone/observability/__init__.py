"""Opt-in observability for VAKRA runs (OpenTelemetry -> Arize Phoenix)."""

from capstone.observability.tracing import (
    TracingConfig,
    is_enabled,
    setup_tracing,
    shutdown_tracing,
    task_span,
)

__all__ = [
    "TracingConfig",
    "is_enabled",
    "setup_tracing",
    "shutdown_tracing",
    "task_span",
]

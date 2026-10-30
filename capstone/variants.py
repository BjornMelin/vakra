"""Agent variants that share one runner (benchmark_runner.py --variant).

  B0  plain ReAct (no post-answer step)
  B1  B0 + the answer-provenance check (capstone.b1)
  B2  B1 + one recovery step (not implemented yet; milestone Nov 18)

A variant is B0 plus an optional *post-answer step*: a callable that takes the
finished task's trajectory record (capstone.trajectories.build_record) and
returns a verdict whose ``answer_returned`` replaces the answer the evaluator
scores. B2 will add its recovery behind the same interface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Mapping, Protocol

from capstone.b1.verifier import Verdict

Variant = Literal["B0", "B1", "B2"]
VARIANTS: tuple[Variant, ...] = ("B0", "B1", "B2")


class PostAnswerStep(Protocol):
    variant: Variant

    def __call__(self, record: Mapping[str, Any]) -> Verdict: ...

    def describe(self) -> dict[str, Any]:
        """Config to embed in the run manifest (no secrets)."""
        ...


def build_post_answer_step(variant: str, verifier_config: str | Path | None = None) -> PostAnswerStep | None:
    """The step for ``variant``; None for B0."""
    if variant == "B0":
        return None
    if variant == "B1":
        from capstone.b1.step import B1Step

        return B1Step.from_config_file(verifier_config)
    if variant == "B2":
        raise NotImplementedError("B2 (B1 + one recovery step) is not implemented yet")
    raise ValueError(f"unknown variant {variant!r}; expected one of {VARIANTS}")

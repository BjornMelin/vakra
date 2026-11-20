"""Agent variants that share one runner (benchmark_runner.py --variant).

  B0  plain ReAct (no post-answer step)
  B1  B0 + the answer-provenance check (capstone.b1)
  B2  B1 + one configured recovery attempt (capstone.b2)

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


def build_post_answer_step(
    variant: str,
    verifier_config: str | Path | None = None,
    *,
    b2_config: str | Path | None = None,
    task_ids: list[str] | None = None,
) -> PostAnswerStep | None:
    """The step for ``variant``; None for B0.

    B2 requires ``b2_config``. The shipped file is UNFROZEN and raises
    until every decision field is set. There is no built-in B2 config.
    """
    if variant == "B0":
        return None
    if variant == "B1":
        from capstone.b1.step import B1Step

        return B1Step.from_config_file(verifier_config)
    if variant == "B2":
        from capstone.b1.step import B1Step
        from capstone.b2.config import B2Config, B2ConfigError
        from capstone.b2.step import B2Step

        if b2_config is None:
            raise B2ConfigError(
                "B2 REFUSING TO LAUNCH: --b2-config is required. "
                "There is no default B2 config."
            )
        return B2Step(
            B2Config.load(b2_config),
            B1Step.from_config_file(verifier_config),
            task_ids=task_ids,
        )
    raise ValueError(f"unknown variant {variant!r}; expected one of {VARIANTS}")

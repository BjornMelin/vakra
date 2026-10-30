"""B1 verifier configuration (one JSON file, embedded in the run's config.json).

Secrets never live here: the judge API key is read at call time from the env
var named by ``judge.api_key_env``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from capstone.b1.evidence import DerivationMode


class JudgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    # OpenAI-compatible server root without "/v1"; None -> $JUDGE_ENDPOINT.
    endpoint: str | None = None
    # None -> $JUDGE_MODEL (the evaluator's judge).
    model: str | None = None
    api_key_env: str = "API_KEY"
    temperature: float = 0.0
    max_tokens: int = 512
    timeout_s: float = 60.0
    # Characters of tool output shown to the judge (the tail is cut).
    max_evidence_chars: int = 12_000


class VerifierConfig(BaseModel):
    """Knobs that plan WS2 leaves open; defaults are the conservative choice."""

    model_config = ConfigDict(extra="forbid")

    # WS2.1 derivation policy: "count" lets list lengths count as traced
    # (the agent answers "how many" by counting rows); "simple" adds sums,
    # means, differences and ratios over the tool numbers; "none" is strict.
    derivations: DerivationMode = "count"
    # Values the user wrote in the query may be repeated in the answer.
    allow_query_values: bool = True
    # Answers whose only checkable values are names: if every name is found the
    # deterministic path accepts; if any is missing, "judge" sends the answer to
    # the judge, "reject" rejects deterministically.
    names_missing: Literal["judge", "reject"] = "judge"
    # Treat a refusal ("I could not find ...") as accept: nothing is claimed.
    accept_abstentions: bool = True
    # WS2.4 reject policy. "flag": keep the B0 answer, record the verdict.
    # "abstain": replace a rejected answer with ``abstain_text``.
    on_reject: Literal["flag", "abstain"] = "flag"
    on_insufficient: Literal["flag", "abstain"] = "flag"
    abstain_text: str = "I could not verify an answer from the tool outputs."
    judge: JudgeConfig = Field(default_factory=JudgeConfig)

    @classmethod
    def load(cls, path: str | Path | None) -> VerifierConfig:
        if path is None:
            return cls()
        return cls.model_validate_json(Path(path).read_text(encoding="utf-8"))

    def sha256(self) -> str:
        blob = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]

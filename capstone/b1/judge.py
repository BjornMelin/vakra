"""Model judge for free-text answers (B1 judge path).

The judge sees the user query, the tool outputs and the answer. It never sees
the gold answer. The prompt template is hashed into every verdict and into the
run's config.json so a run records exactly what was asked.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from capstone.b1.config import JudgeConfig

JudgeLabel = Literal["supported", "unsupported", "insufficient"]

JUDGE_PROMPT = """You check whether an assistant's final answer is supported by the tool outputs it received.

Rules:
- Use only the USER QUESTION and TOOL OUTPUTS below. Do not use outside knowledge.
- "supported": every factual claim in the answer is stated in, or follows directly from, the tool outputs or the question.
- "unsupported": the answer states a fact, name, number or conclusion that the tool outputs contradict or do not contain.
- "insufficient": the tool outputs are empty, errors, or too incomplete to decide.
- Do not judge whether the answer is correct in the world, only whether it is supported.

USER QUESTION:
{query}

TOOL OUTPUTS:
{evidence}

ANSWER:
{answer}

Reply with one JSON object and nothing else:
{{"verdict": "supported" | "unsupported" | "insufficient", "unsupported_claim": "<the first unsupported claim, or empty>", "reason": "<one sentence>"}}"""

PROMPT_SHA256 = hashlib.sha256(JUDGE_PROMPT.encode()).hexdigest()[:16]

_JSON = re.compile(r"\{.*\}", re.DOTALL)
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class JudgeResult(BaseModel):
    verdict: JudgeLabel
    unsupported_claim: str = ""
    reason: str = ""
    model: str | None = None
    prompt_sha256: str = PROMPT_SHA256
    latency_s: float = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw: str | None = None
    error: str | None = None


class Judge(Protocol):
    """Anything that can judge one (query, evidence, answer) triple."""

    model: str | None

    def __call__(self, *, query: str, evidence: str, answer: str) -> JudgeResult: ...


def render_prompt(*, query: str, evidence: str, answer: str) -> str:
    return JUDGE_PROMPT.format(query=query, evidence=evidence, answer=answer)


def parse_judge_reply(text: str) -> tuple[JudgeLabel, str, str]:
    """Parse the judge's JSON reply. Unparseable replies are ``insufficient``."""
    body = _THINK.sub("", text or "")
    m = _JSON.search(body)
    if m:
        try:
            obj = json.loads(m.group())
            verdict = str(obj.get("verdict", "")).strip().lower()
            if verdict in ("supported", "unsupported", "insufficient"):
                return verdict, str(obj.get("unsupported_claim") or ""), str(obj.get("reason") or "")  # type: ignore[return-value]
        except ValueError:
            pass
    low = body.lower()
    for label in ("unsupported", "insufficient", "supported"):
        if re.search(rf"\b{label}\b", low):
            return label, "", "parsed from free text"  # type: ignore[return-value]
    return "insufficient", "", "unparseable judge reply"


class OpenAICompatibleJudge:
    """Judge backed by any OpenAI-compatible chat endpoint (vLLM, Groq, ...)."""

    def __init__(self, cfg: JudgeConfig) -> None:
        from langchain_openai import ChatOpenAI  # imported lazily: optional at test time

        endpoint = cfg.endpoint or os.getenv("JUDGE_ENDPOINT")
        model = cfg.model or os.getenv("JUDGE_MODEL")
        if not endpoint or not model:
            raise ValueError("B1 judge needs judge.endpoint/model or JUDGE_ENDPOINT/JUDGE_MODEL")
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self._cfg = cfg
        self._llm = ChatOpenAI(
            model=model,
            base_url=self.endpoint + "/v1",
            api_key=os.getenv(cfg.api_key_env) or "EMPTY",
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            timeout=cfg.timeout_s,
            max_retries=2,
        )

    def __call__(self, *, query: str, evidence: str, answer: str) -> JudgeResult:
        prompt = render_prompt(query=query, evidence=evidence[: self._cfg.max_evidence_chars], answer=answer)
        t0 = time.perf_counter()
        try:
            msg = self._llm.invoke(prompt)
        except Exception as exc:  # network / server errors become "insufficient"
            return JudgeResult(
                verdict="insufficient",
                model=self.model,
                latency_s=time.perf_counter() - t0,
                error=f"{type(exc).__name__}: {exc}",
            )
        text = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
        verdict, claim, reason = parse_judge_reply(text)
        usage: dict[str, Any] = getattr(msg, "usage_metadata", None) or {}
        return JudgeResult(
            verdict=verdict,
            unsupported_claim=claim,
            reason=reason,
            model=self.model,
            latency_s=time.perf_counter() - t0,
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            raw=text[:2000],
        )


def build_judge(cfg: JudgeConfig) -> Judge | None:
    """The configured judge, or None when disabled."""
    return OpenAICompatibleJudge(cfg) if cfg.enabled else None

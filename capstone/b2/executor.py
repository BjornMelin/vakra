"""One recovery attempt against an agent. Unit tests pass a fake instead."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class RecoveryAttempt:
    answer: str | None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    llm_calls: int = 0
    error: str | None = None


class RecoveryExecutor(Protocol):
    async def attempt(
        self,
        *,
        prompt: str,
        max_tool_calls: int,
        max_llm_calls: int,
        timeout_s: float,
    ) -> RecoveryAttempt: ...


def recovery_recursion_limit(max_tool_calls: int, max_llm_calls: int) -> int:
    """Superstep budget for one attempt, from the configured caps.

    A round is a model superstep plus a tool superstep, then one more model
    call to answer. The tighter of the two caps wins. The step still discards
    a result that reports more calls than the cap.
    """
    by_tools = 2 * max_tool_calls + 1
    by_llm = 2 * max_llm_calls - 1
    return max(1, min(by_tools, by_llm))


class AgentRecoveryExecutor:
    """Live executor. Not used by the unit tests.

    Calls ``agent.run`` once. The step enforces the tool, model, and time caps
    on the returned attempt.
    """

    def __init__(self, agent: Any) -> None:
        self.agent = agent

    async def attempt(
        self,
        *,
        prompt: str,
        max_tool_calls: int,
        max_llm_calls: int,
        timeout_s: float,
    ) -> RecoveryAttempt:
        del timeout_s  # the step applies the timeout around this call
        limit = recovery_recursion_limit(max_tool_calls, max_llm_calls)
        response = await self.agent.run(prompt, recursion_limit=limit)
        calls = []
        for tc in response.tool_calls or []:
            calls.append(
                {
                    "name": tc.get("tool_name") or tc.get("name") or "",
                    "arguments": tc.get("arguments") or tc.get("args") or {},
                    "result": tc.get("result"),
                }
            )
        llm_calls = sum(
            1 for entry in (response.trajectory or []) if entry.get("type") == "AIMessage"
        )
        return RecoveryAttempt(
            answer=response.content, tool_calls=calls, llm_calls=llm_calls
        )

"""How a ReAct call is bounded.

``max_iterations`` unset and ``recursion_limit`` unset is the B0/B1 path:
the harness passes no ``recursion_limit``, and LangGraph's library default
applies. Do not fill a number in here. That would change runs that today
leave the limit unset.

The pin is ``langgraph>=1.0.9``. In the 1.0.9 tag the library default is
``int(getenv("LANGGRAPH_DEFAULT_RECURSION_LIMIT", "10000"))``. A later
release (1.2.24, what that pin resolved to on 2026-11-20) uses the sentinel
10007 so an explicit limit of 10000 is not mistaken for "unset". The library
default was 25 before 1.0.6 (January 2026) and 1000 in the 1.0.6 change.
``create_react_agent`` does not
raise when a tool call would cross the limit. ``remaining_steps`` is
``recursion_limit - superstep``. When that is below 2 and the model still
requested tools, the response is replaced with
``"Sorry, need more steps to process this request."``

A tool-calling loop on that graph is one model superstep, one tool
superstep, and so on. ``recursion_limit`` 25 therefore ends a loop that never
stops itself at 13 model calls and 12 tool calls. ``recursion_limit`` 47 ends
it at 24 model calls and 23 tool calls. Nothing in this repository sets 47.
Saved Session A logs show ``max_iterations=None``, so the harness formula
``max_iterations * 2 + 1`` did not run. The 24/23 stops are not produced by
a constant in this tree. The droplet's installed LangGraph build and
``LANGGRAPH_DEFAULT_RECURSION_LIMIT`` are not recorded here.
"""

from __future__ import annotations


def graph_invocation_config(
    max_iterations: int | None, recursion_limit: int | None
) -> dict[str, int] | None:
    """Config for ``agent.ainvoke``, or None to leave the library default.

    An explicit ``recursion_limit`` wins. Otherwise a set ``max_iterations``
    maps to ``max_iterations * 2 + 1``, which is the existing harness formula.
    Both unset returns None, which is the B0/B1 behavior when the flags are
    omitted.
    """
    if recursion_limit is not None:
        return {"recursion_limit": int(recursion_limit)}
    if max_iterations is not None:
        return {"recursion_limit": int(max_iterations) * 2 + 1}
    return None

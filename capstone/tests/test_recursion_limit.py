"""Unset iteration flags keep the library recursion limit. No LangGraph import."""

import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[2] / "agents" / "limits.py"
_spec = importlib.util.spec_from_file_location("agent_limits", _path)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
graph_invocation_config = _mod.graph_invocation_config


def test_both_unset_passes_no_recursion_limit():
    assert graph_invocation_config(None, None) is None


def test_max_iterations_uses_the_existing_formula():
    assert graph_invocation_config(4, None) == {"recursion_limit": 9}


def test_explicit_recursion_limit_wins_and_is_not_rewritten():
    assert graph_invocation_config(None, 47) == {"recursion_limit": 47}
    assert graph_invocation_config(4, 47) == {"recursion_limit": 47}

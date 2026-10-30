"""Compatibility helpers for differences between MCP Python SDK releases.

MCP SDK 1.x exposes a tool's JSON Schema as ``Tool.inputSchema``. MCP SDK 2.x
renamed the attribute to ``Tool.input_schema`` and kept ``inputSchema`` only as
the wire-format alias, so attribute access to ``inputSchema`` raises
``AttributeError`` (and ``hasattr`` silently returns False). Plain dicts (the
JSON wire format, e.g. cached tool lists) always use ``inputSchema``.

This module has no third-party dependencies so it can be imported by the
benchmark client, the evaluator, and the MCP server images alike.
"""

from typing import Any

_SCHEMA_ATTRS = ("input_schema", "inputSchema")


def tool_input_schema(tool: Any) -> dict[str, Any] | None:
    """Return a tool's input JSON Schema as a plain dict, or None if absent.

    Accepts MCP SDK 1.x and 2.x ``Tool`` objects and wire-format dicts. A
    Pydantic model schema is converted with ``model_dump()``.
    """
    if isinstance(tool, dict):
        schema = next(
            (tool[k] for k in ("inputSchema", "input_schema") if k in tool), None
        )
    else:
        schema = next(
            (getattr(tool, attr) for attr in _SCHEMA_ATTRS if _has_attr(tool, attr)),
            None,
        )
    if schema is None:
        return None
    if hasattr(schema, "model_dump"):
        schema = schema.model_dump()
    return schema


def _has_attr(obj: Any, name: str) -> bool:
    # hasattr() on a Pydantic model calls __getattr__, which raises
    # AttributeError for unknown names; that is exactly the signal we want.
    try:
        getattr(obj, name)
    except AttributeError:
        return False
    return True

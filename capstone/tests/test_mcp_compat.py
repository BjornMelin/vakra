"""MCP SDK 1.x/2.x compatibility for tool input schemas."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from environment.mcp_compat import tool_input_schema

SCHEMA = {
    "type": "object",
    "properties": {"team": {"type": "string", "description": "Team name"}},
    "required": ["team"],
}


def test_dict_wire_format():
    assert tool_input_schema({"name": "t", "inputSchema": SCHEMA}) == SCHEMA
    assert tool_input_schema({"name": "t", "input_schema": SCHEMA}) == SCHEMA
    assert tool_input_schema({"name": "t"}) is None


def test_sdk1_style_object():
    assert tool_input_schema(SimpleNamespace(name="t", inputSchema=SCHEMA)) == SCHEMA


def test_sdk2_style_object():
    assert tool_input_schema(SimpleNamespace(name="t", input_schema=SCHEMA)) == SCHEMA


def test_missing_schema():
    assert tool_input_schema(SimpleNamespace(name="t")) is None


def test_pydantic_schema_is_dumped():
    class FakeModel:
        def model_dump(self):
            return SCHEMA

    assert (
        tool_input_schema(SimpleNamespace(name="t", input_schema=FakeModel())) == SCHEMA
    )


def test_installed_mcp_tool():
    types = pytest.importorskip("mcp.types")
    tool = types.Tool.model_validate({"name": "get_goals", "inputSchema": SCHEMA})
    assert tool_input_schema(tool) == SCHEMA


def test_agent_wrapper_builds_args_schema_from_installed_mcp_tool():
    """Regression: under MCP SDK 2.x the wrapper used to drop every parameter."""
    types = pytest.importorskip("mcp.types")
    pytest.importorskip("langchain_core")
    from agents.mcp_tool_wrapper import MCPToolWrapper

    tool = types.Tool.model_validate(
        {"name": "get_goals", "description": "Goals for a team", "inputSchema": SCHEMA}
    )
    wrapper = MCPToolWrapper(session=None)
    lc_tool = wrapper._create_langchain_tool(tool)
    assert set(lc_tool.args) == {"team"}

"""Final answers must be plain text even when the model returns content blocks."""

import pytest

pytest.importorskip("langgraph")

from agents.agent_interface import _content_text  # noqa: E402


def test_string_content_is_unchanged():
    assert _content_text("42") == "42"


def test_reasoning_blocks_are_dropped():
    content = [
        {"type": "thinking", "thinking": "work it out"},
        {"type": "text", "text": "The answer is "},
        {"type": "text", "text": "42."},
    ]
    assert _content_text(content) == "The answer is 42."


def test_empty_and_reasoning_only_content_is_empty():
    assert _content_text(None) == ""
    assert _content_text([]) == ""
    assert _content_text([{"type": "thinking", "thinking": "x"}]) == ""

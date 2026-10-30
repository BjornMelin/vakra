"""The groq judge backend must honour JUDGE_ENDPOINT / JUDGE_MODEL."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

pytest.importorskip("langchain_openai")


@pytest.fixture()
def chat_groq(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT / "evaluator"))
    sys.modules.pop("judge", None)
    import judge

    monkeypatch.setenv("API_KEY", "dummy")
    return judge.ChatGroq


def test_defaults_to_groq(chat_groq, monkeypatch):
    monkeypatch.delenv("JUDGE_ENDPOINT", raising=False)
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    llm = chat_groq({})
    assert str(llm.openai_api_base) == "https://api.groq.com/openai/v1"
    assert llm.model_name == "openai/gpt-oss-120b"


def test_env_overrides(chat_groq, monkeypatch):
    monkeypatch.setenv("JUDGE_ENDPOINT", "http://localhost:8000/")
    monkeypatch.setenv("JUDGE_MODEL", "gpt-oss-120b")
    llm = chat_groq({})
    assert str(llm.openai_api_base) == "http://localhost:8000/v1"
    assert llm.model_name == "gpt-oss-120b"


def test_explicit_config_wins(chat_groq, monkeypatch):
    monkeypatch.setenv("JUDGE_ENDPOINT", "http://localhost:8000")
    llm = chat_groq({"end_point": "http://judge:9000", "model_name": "m"})
    assert str(llm.openai_api_base) == "http://judge:9000/v1"
    assert llm.model_name == "m"

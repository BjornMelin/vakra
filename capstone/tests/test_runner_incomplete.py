"""A domain that returns fewer results than items is not written and fails the run."""

import asyncio
from types import SimpleNamespace

import pytest

import benchmark_runner as br


def _run(monkeypatch, tmp_path, n_items, n_results):
    items = [SimpleNamespace(domain="d1") for _ in range(n_items)]
    saved = []
    monkeypatch.setattr(br, "load_benchmark_data", lambda **_: (items, None))
    monkeypatch.setattr(br, "make_output_dir", lambda *_: tmp_path)
    monkeypatch.setattr(br, "create_llm", lambda **_: object())

    async def fake_domain(**kw):
        return [SimpleNamespace(status="success")] * n_results

    monkeypatch.setattr(br, "run_benchmark_for_domain", fake_domain)
    monkeypatch.setattr(br, "save_results_ground_truth", lambda res, out: saved.append(len(res)))
    monkeypatch.setattr(br, "save_tools_log", lambda res, out: None)
    coro = br.run_capability(capability_id=2, cfg=SimpleNamespace(mode="stdio", command=None, container_name="c"))
    return coro, saved


def test_incomplete_domain_not_written_and_raises(monkeypatch, tmp_path):
    coro, saved = _run(monkeypatch, tmp_path, n_items=3, n_results=0)
    with pytest.raises(br.IncompleteRunError):
        asyncio.run(coro)
    assert saved == []


def test_complete_domain_written(monkeypatch, tmp_path):
    coro, saved = _run(monkeypatch, tmp_path, n_items=3, n_results=3)
    assert len(asyncio.run(coro)) == 3
    assert saved == [3]

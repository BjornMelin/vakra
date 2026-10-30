"""Train-split capability-1 uuids must be addressable as tool universes."""

import importlib.util
import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "environment/configs/generate_task_1_tool_universe_mapping.py"


def _load_generator(repo_root: Path):
    spec = importlib.util.spec_from_file_location("gen_mapping", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.REPO_ROOT = repo_root
    return mod


def _item(uuid: str, tool: str) -> dict:
    return {
        "uuid": uuid,
        "domain": "books",
        "turns": [{"query": f"q-{uuid}"}],
        "output": [
            {
                "sequence": {
                    "tool_call": [
                        {
                            "name": "initialize_active_data",
                            "arguments": {"condition": "c", "database_path": "/db"},
                        },
                        {"name": tool, "arguments": {}},
                    ]
                }
            }
        ],
    }


def test_merge_keeps_existing_and_adds_train(tmp_path):
    out_dir = tmp_path / "data/train/capability_1_bi_apis/output"
    out_dir.mkdir(parents=True)
    (out_dir / "books.json").write_text(json.dumps([_item("train-1", "select_data_equal_to")]))
    mapping = tmp_path / "environment/configs/mcp_tool_universe_id_mapping.yaml"
    mapping.parent.mkdir(parents=True)
    mapping.write_text(yaml.safe_dump({"test-1": {"domain": "books"}}))

    gen = _load_generator(tmp_path)
    gen.generate_mapping(splits=("train",), merge=True)

    result = yaml.safe_load(mapping.read_text())
    assert set(result) == {"test-1", "train-1"}
    assert result["test-1"] == {"domain": "books"}
    assert result["train-1"]["domain"] == "books"

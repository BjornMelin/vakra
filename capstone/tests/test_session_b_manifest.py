"""Registered task manifests: the verified 414 and the D6 855 evaluation set."""

import json
from types import SimpleNamespace

import pytest

from capstone.b2.control import control_trigger_ids
from capstone.session_b.manifest import (
    D6_EVAL_855_COUNTS,
    D6_EVAL_855_NAME,
    D6_EVAL_855_SHA256,
    DEFAULT_MEMBERSHIP,
    EXPECTED_COUNTS,
    RECORDED_SHA256,
    ManifestError,
    assert_exact_ids,
    file_sha256,
    load_membership,
    load_run_plan,
    load_verified_414,
    read_subset,
    select_for_capability,
)


def test_committed_membership_hash_and_counts():
    membership = load_verified_414()
    assert membership.sha256 == RECORDED_SHA256
    assert file_sha256(membership.path) == RECORDED_SHA256
    assert membership.counts() == EXPECTED_COUNTS
    assert sum(EXPECTED_COUNTS.values()) == 414
    assert len(membership.ids) == 414
    sidecar = membership.path.with_name("verified-common-414-membership.sha256")
    assert RECORDED_SHA256 in sidecar.read_text(encoding="utf-8")


def test_hash_mismatch_and_bad_counts_refuse(tmp_path):
    src = load_verified_414()
    rows = json.loads(src.path.read_text(encoding="utf-8"))
    tampered = tmp_path / "m.json"
    tampered.write_text(json.dumps(rows[:-1]), encoding="utf-8")
    with pytest.raises(ManifestError, match="sha256"):
        load_verified_414(tampered)
    with pytest.raises(ManifestError, match="counts"):
        load_membership(tampered, recorded_sha256=None, expected_counts=EXPECTED_COUNTS)


def test_select_refuses_missing_and_extra():
    membership = load_verified_414()
    plan = load_run_plan(membership.path)
    cap1 = sorted(plan.ids_by_capability[1])
    present = [SimpleNamespace(uuid=u, domain="d") for u in cap1[:-1]]
    with pytest.raises(ManifestError, match="missing"):
        select_for_capability(present, 1, plan)
    extra_id = "not-in-the-414"
    with pytest.raises(ManifestError, match="extra"):
        assert_exact_ids(cap1, [*cap1, extra_id], where="capability 1")
    items = [SimpleNamespace(uuid=u, domain="d") for u in cap1]
    items.append(SimpleNamespace(uuid="train-only", domain="d"))
    selected = select_for_capability(items, 1, plan)
    assert {i.uuid for i in selected} == set(cap1)
    assert all(i.uuid != "train-only" for i in selected)


def test_q7_subset_must_be_inside_the_414(tmp_path):
    membership = load_verified_414()
    chosen = sorted(membership.ids)[:4]
    path = tmp_path / "q7.json"
    path.write_text(json.dumps([{"uuid": u} for u in chosen]), encoding="utf-8")
    assert read_subset(path, membership) == chosen
    plan = load_run_plan(membership.path, path)
    assert plan.ids == frozenset(chosen)
    assert plan.subset_path == str(path)

    bad = tmp_path / "q7.txt"
    bad.write_text(chosen[0] + "\nnot-a-member\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="not in the registered manifest"):
        read_subset(bad, membership)

    dup = tmp_path / "dup.txt"
    dup.write_text(chosen[0] + "\n" + chosen[0] + "\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="duplicate"):
        read_subset(dup, membership)


def test_414_still_loads_and_refuses_one_byte_edit(tmp_path):
    plan = load_run_plan(DEFAULT_MEMBERSHIP)
    assert plan.membership.sha256 == RECORDED_SHA256
    assert plan.membership.counts() == EXPECTED_COUNTS
    assert plan.as_dict()["n_ids"] == 414
    assert plan.as_dict()["membership_sha256"] == RECORDED_SHA256

    raw = bytearray(DEFAULT_MEMBERSHIP.read_bytes())
    raw[-2] ^= 0x01
    edited = tmp_path / DEFAULT_MEMBERSHIP.name
    edited.write_bytes(bytes(raw))
    with pytest.raises(ManifestError, match="sha256"):
        load_run_plan(edited)


def test_d6_eval_855_loads_with_recorded_counts(tmp_path):
    path = DEFAULT_MEMBERSHIP.with_name(D6_EVAL_855_NAME)
    plan = load_run_plan(path)
    assert plan.membership.sha256 == D6_EVAL_855_SHA256
    assert file_sha256(path) == D6_EVAL_855_SHA256
    assert plan.membership.counts() == D6_EVAL_855_COUNTS
    assert plan.as_dict()["n_ids"] == 855
    assert plan.as_dict()["counts"] == {
        str(cap): count for cap, count in D6_EVAL_855_COUNTS.items()
    }
    sidecar = path.with_name("d6-eval-855-membership.sha256")
    assert D6_EVAL_855_SHA256 in sidecar.read_text(encoding="utf-8")

    raw = bytearray(path.read_bytes())
    raw[10] ^= 0x01
    edited = tmp_path / path.name
    edited.write_bytes(bytes(raw))
    with pytest.raises(ManifestError, match="sha256"):
        load_run_plan(edited)


def test_unregistered_manifest_refuses(tmp_path):
    alien = tmp_path / "not-in-the-registry.json"
    alien.write_bytes(DEFAULT_MEMBERSHIP.with_name(D6_EVAL_855_NAME).read_bytes())
    with pytest.raises(ManifestError, match="manifest registry"):
        load_run_plan(alien)


def test_select_for_capability_on_855_returns_planned_uuids():
    plan = load_run_plan(DEFAULT_MEMBERSHIP.with_name(D6_EVAL_855_NAME))
    capability = 1
    planned = sorted(plan.ids_by_capability[capability])
    items = [SimpleNamespace(uuid=uuid, domain="fixture") for uuid in planned]
    items.append(SimpleNamespace(uuid="train-only-not-in-855", domain="fixture"))
    selected = select_for_capability(items, capability, plan)
    assert [item.uuid for item in selected] == planned
    assert all(item.uuid != "train-only-not-in-855" for item in selected)


def test_control_trigger_ids_stable_on_855_universe():
    plan = load_run_plan(DEFAULT_MEMBERSHIP.with_name(D6_EVAL_855_NAME))
    universe = list(plan.ids)
    assert len(universe) == 855
    first = control_trigger_ids(universe, 5, 20261119)
    second = control_trigger_ids(universe, 5, 20261119)
    reversed_ids = control_trigger_ids(list(reversed(universe)), 5, 20261119)
    assert first == second == reversed_ids
    assert len(first) == 5
    assert first <= plan.ids

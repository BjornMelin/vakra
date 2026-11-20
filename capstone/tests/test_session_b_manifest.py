"""Verified 414-id manifest and a Q7 subset list."""

import json
from types import SimpleNamespace

import pytest

from capstone.session_b.manifest import (
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
    with pytest.raises(ManifestError, match="not in the verified 414"):
        read_subset(bad, membership)

    dup = tmp_path / "dup.txt"
    dup.write_text(chosen[0] + "\n" + chosen[0] + "\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="duplicate"):
        read_subset(dup, membership)

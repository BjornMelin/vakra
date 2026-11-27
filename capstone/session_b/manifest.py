"""Session B task list.

A run loads a registered membership file. The file name selects the recorded
SHA-256 and the per-capability counts; both are checked on load. A run must
execute exactly the ids in that file, or exactly a Q7 subset file whose every
id is a member. Ids in the train files that are not in the plan are not
executed. An id in the plan that is not in the loaded tasks, or an id that
would be executed but is not in the plan, refuses the run.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RECORDED_SHA256 = "00480a28b6b06fdee385402258e779c99a69d1792b434b70720b781c6d9d5b6a"
EXPECTED_COUNTS = {1: 101, 2: 128, 3: 73, 4: 112}
DEFAULT_MEMBERSHIP = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "manifests"
    / "verified-common-414-membership.json"
)
D6_EVAL_855_NAME = "d6-eval-855-membership.json"
D6_EVAL_855_SHA256 = "a0b73f7082d953a4136aaa029acf3d474873c5a3b05dbcbfad05e141938100b4"
D6_EVAL_855_COUNTS = {1: 322, 2: 264, 3: 133, 4: 136}

# File name -> (recorded sha256, expected per-capability counts).
MANIFEST_REGISTRY: dict[str, tuple[str, Mapping[int, int]]] = {
    DEFAULT_MEMBERSHIP.name: (RECORDED_SHA256, EXPECTED_COUNTS),
    D6_EVAL_855_NAME: (D6_EVAL_855_SHA256, D6_EVAL_855_COUNTS),
}


class ManifestError(RuntimeError):
    """The task list is unregistered or does not match its recorded checks."""


@dataclass(frozen=True)
class Membership:
    path: Path
    sha256: str
    ids: frozenset[str]
    capability_of: Mapping[str, int]
    ids_by_capability: Mapping[int, frozenset[str]]

    def counts(self) -> dict[int, int]:
        return {cap: len(ids) for cap, ids in sorted(self.ids_by_capability.items())}


@dataclass(frozen=True)
class TaskPlan:
    """Ids that will be executed, and the membership they were drawn from."""

    membership: Membership
    ids: frozenset[str]
    ids_by_capability: Mapping[int, frozenset[str]]
    subset_path: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "membership_sha256": self.membership.sha256,
            "membership_path": str(self.membership.path),
            "n_ids": len(self.ids),
            "counts": {
                str(cap): len(ids) for cap, ids in sorted(self.ids_by_capability.items())
            },
            "subset_path": self.subset_path,
        }


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_membership(
    path: str | Path,
    *,
    recorded_sha256: str | None,
    expected_counts: Mapping[int, int] | None,
) -> Membership:
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ManifestError(f"REFUSING TO RUN: cannot read manifest {path}: {exc}") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if recorded_sha256 is not None and digest != recorded_sha256:
        raise ManifestError(
            "REFUSING TO RUN: manifest sha256 "
            f"{digest} != recorded {recorded_sha256} ({path})."
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"REFUSING TO RUN: manifest {path} is not JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ManifestError(f"REFUSING TO RUN: manifest {path} must be a JSON list.")
    capability_of: dict[str, int] = {}
    by_cap: dict[int, set[str]] = defaultdict(set)
    for i, row in enumerate(data):
        if not isinstance(row, dict) or "uuid" not in row or "capability" not in row:
            raise ManifestError(
                f"REFUSING TO RUN: manifest row {i} needs capability and uuid."
            )
        uuid = str(row["uuid"])
        try:
            cap = int(row["capability"])
        except (TypeError, ValueError) as exc:
            raise ManifestError(
                f"REFUSING TO RUN: manifest row {i} capability is not an int."
            ) from exc
        if uuid in capability_of:
            raise ManifestError(f"REFUSING TO RUN: duplicate uuid {uuid}.")
        capability_of[uuid] = cap
        by_cap[cap].add(uuid)
    counts = {cap: len(ids) for cap, ids in by_cap.items()}
    if expected_counts is not None and counts != dict(expected_counts):
        raise ManifestError(
            "REFUSING TO RUN: capability counts "
            f"{counts} != required {dict(expected_counts)}."
        )
    return Membership(
        path=path,
        sha256=digest,
        ids=frozenset(capability_of),
        capability_of=capability_of,
        ids_by_capability={cap: frozenset(ids) for cap, ids in by_cap.items()},
    )


def load_verified_414(path: str | Path | None = None) -> Membership:
    """The committed 414-id file. Hash and counts are not optional."""
    return load_membership(
        DEFAULT_MEMBERSHIP if path is None else path,
        recorded_sha256=RECORDED_SHA256,
        expected_counts=EXPECTED_COUNTS,
    )


def read_subset(path: str | Path, membership: Membership) -> list[str]:
    """Q7 cap-hit list. Every id must already be a member of ``membership``.

    Accepts a JSON list of strings, a JSON list of objects with ``uuid``,
    a JSON object with a ``uuids`` list, or one id per line.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"REFUSING TO RUN: cannot read subset {path}: {exc}") from exc
    ids = _parse_id_list(text, path)
    if len(ids) != len(set(ids)):
        raise ManifestError(f"REFUSING TO RUN: subset {path} has duplicate uuids.")
    extra = [u for u in ids if u not in membership.ids]
    if extra:
        preview = ", ".join(extra[:10])
        raise ManifestError(
            "REFUSING TO RUN: subset has "
            f"{len(extra)} uuid(s) that are not in the registered manifest: {preview}."
        )
    if not ids:
        raise ManifestError(f"REFUSING TO RUN: subset {path} is empty.")
    return ids


def load_run_plan(
    membership_path: str | Path, subset_path: str | Path | None = None
) -> TaskPlan:
    path = Path(membership_path)
    registered = MANIFEST_REGISTRY.get(path.name)
    if registered is None:
        known = ", ".join(sorted(MANIFEST_REGISTRY))
        raise ManifestError(
            "REFUSING TO RUN: "
            f"{path.name} is not in the manifest registry ({known})."
        )
    recorded_sha256, expected_counts = registered
    membership = load_membership(
        path,
        recorded_sha256=recorded_sha256,
        expected_counts=expected_counts,
    )
    if subset_path is None:
        by_cap = membership.ids_by_capability
        ids = membership.ids
        subset_name = None
    else:
        chosen = read_subset(subset_path, membership)
        by_cap_sets: dict[int, set[str]] = defaultdict(set)
        for uuid in chosen:
            by_cap_sets[membership.capability_of[uuid]].add(uuid)
        by_cap = {cap: frozenset(v) for cap, v in by_cap_sets.items()}
        ids = frozenset(chosen)
        subset_name = str(subset_path)
    return TaskPlan(
        membership=membership,
        ids=ids,
        ids_by_capability=by_cap,
        subset_path=subset_name,
    )


def assert_exact_ids(planned: Iterable[str], actual: Iterable[str], *, where: str) -> None:
    planned_set = set(planned)
    actual_set = set(actual)
    missing = sorted(planned_set - actual_set)
    extra = sorted(actual_set - planned_set)
    if missing or extra:
        raise ManifestError(
            "REFUSING TO RUN: "
            f"{where} has {len(missing)} missing and {len(extra)} extra uuid(s). "
            f"missing={missing[:20]} extra={extra[:20]}."
        )


def select_for_capability(items: list[Any], capability: int, plan: TaskPlan) -> list[Any]:
    """Items whose uuid is in the plan for this capability, in input order.

    A planned uuid that is not in ``items`` refuses the run. ``items`` may
    contain uuids outside the plan; those are not returned. The returned set
    is checked to be exactly the planned set.
    """
    planned = plan.ids_by_capability.get(capability, frozenset())
    seen: set[str] = set()
    for item in items:
        uuid = str(item.uuid)
        if uuid in seen:
            raise ManifestError(
                f"REFUSING TO RUN: duplicate uuid {uuid} in capability {capability} data."
            )
        seen.add(uuid)
    selected = [item for item in items if str(item.uuid) in planned]
    assert_exact_ids(
        planned, (str(item.uuid) for item in selected), where=f"capability {capability}"
    )
    return selected


def _parse_id_list(text: str, path: Path) -> list[str]:
    stripped = text.lstrip()
    if not stripped:
        return []
    if stripped[0] not in "[{":
        return _lines(path)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"REFUSING TO RUN: subset {path} is not JSON: {exc}") from exc
    if isinstance(data, dict):
        if "uuids" not in data:
            raise ManifestError(
                f"REFUSING TO RUN: subset {path} object needs a 'uuids' list."
            )
        data = data["uuids"]
    if not isinstance(data, list):
        raise ManifestError(f"REFUSING TO RUN: subset {path} must be a list of uuids.")
    ids: list[str] = []
    for row in data:
        if isinstance(row, str):
            ids.append(row)
        elif isinstance(row, dict) and row.get("uuid"):
            ids.append(str(row["uuid"]))
        else:
            raise ManifestError(
                f"REFUSING TO RUN: subset {path} has a row that is not a uuid."
            )
    return ids


def _lines(path: Path) -> list[str]:
    ids = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        first = line.split(",", 1)[0].strip()
        if first.lower() != "uuid":
            ids.append(first)
    return ids

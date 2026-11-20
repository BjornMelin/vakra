"""Seeded control arm. The sample size is an argument, never a hidden count."""

from __future__ import annotations

import random
from collections.abc import Sequence

from capstone.b2.config import B2ConfigError


def control_trigger_ids(task_ids: Sequence[str], n: int, seed: int) -> frozenset[str]:
    """``n`` ids from the sorted unique universe, stable for ``(universe, n, seed)``.

    Input order does not matter. ``n`` is the matched B1 flag count and must
    be passed in. This does not look at verdicts.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise B2ConfigError(
            f"B2 REFUSING TO LAUNCH: control_seed must be an int. Got {seed!r}."
        )
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise B2ConfigError(
            "B2 REFUSING TO LAUNCH: matched_trigger_count must be an int >= 0. "
            f"Got {n!r}."
        )
    universe = sorted({str(u) for u in task_ids})
    if n > len(universe):
        raise B2ConfigError(
            "B2 REFUSING TO LAUNCH: matched_trigger_count "
            f"{n} exceeds the task universe ({len(universe)})."
        )
    rng = random.Random(seed)
    pool = list(universe)
    for i in range(n):
        j = rng.randrange(i, len(pool))
        pool[i], pool[j] = pool[j], pool[i]
    return frozenset(pool[:n])

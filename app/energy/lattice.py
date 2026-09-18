"""Meet-semilattice operations over constraint tensors.

See TASKS.md D3.2 and docs/ARCHITECTURE_CLAMP.md section 3.2 (the Meet
Theorem). Every constraint family is a per-hour, one-sided bound, so taking
the elementwise tighter bound across a set of tensors gives a schedule that
satisfies every one of them simultaneously. Infeasibility is monotone: if a
subset's meet is infeasible, every superset's meet is infeasible too, which
is what makes ``is_pruned`` a sound shortcut rather than a heuristic.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from itertools import combinations

import numpy as np

from app.contracts import ConstraintTensor


def meet(tensors: list[ConstraintTensor]) -> ConstraintTensor:
    """Elementwise greatest lower bound: tighter ceilings, higher floors.

    A schedule feasible under ``meet(tensors)`` satisfies every tensor in
    ``tensors`` simultaneously (Meet Theorem, ARCHITECTURE_CLAMP.md #3.2).
    """
    if not tensors:
        raise ValueError("meet requires at least one tensor")
    return ConstraintTensor(
        solar=np.minimum.reduce([t.solar for t in tensors]),
        reserve=np.maximum.reduce([t.reserve for t in tensors]),
        charge=np.minimum.reduce([t.charge for t in tensors]),
        discharge=np.minimum.reduce([t.discharge for t in tensors]),
        grid=np.minimum.reduce([t.grid for t in tensors]),
    )


def subsets_containing_anchor(num_candidates: int, anchor: int = 0) -> Iterator[frozenset[int]]:
    """Every subset of ``{0, ..., num_candidates-1}`` that contains ``anchor``.

    Yielded in order of increasing size, so cheaper (more likely feasible)
    subsets are tried before larger ones — the order a monotone-infeasibility
    scan wants, since finding a large infeasible subset prunes many
    not-yet-tried supersets, while finding a small one prunes fewer.
    """
    others = [i for i in range(num_candidates) if i != anchor]
    for size in range(len(others) + 1):
        for combo in combinations(others, size):
            yield frozenset((anchor, *combo))


def is_pruned(subset: frozenset[int], known_infeasible: Iterable[frozenset[int]]) -> bool:
    """True if ``subset`` is a superset of an already-known-infeasible subset.

    Corollary of the Meet Theorem: feasibility can only shrink as more
    tensors join the meet, so no superset of an infeasible subset needs to
    be solved.
    """
    return any(known <= subset for known in known_infeasible)

import numpy as np
import pytest

from app.contracts import ConstraintTensor
from app.energy import lattice


def _tensor(solar=20.0, reserve=10.0, charge=30.0, discharge=30.0, grid=np.inf) -> ConstraintTensor:
    return ConstraintTensor(
        solar=np.full(24, solar),
        reserve=np.full(24, reserve),
        charge=np.full(24, charge),
        discharge=np.full(24, discharge),
        grid=np.full(24, grid),
    )


def test_meet_takes_min_on_ceilings_and_max_on_reserve():
    a = _tensor(solar=20.0, reserve=10.0, charge=30.0, discharge=30.0, grid=100.0)
    b = _tensor(solar=15.0, reserve=25.0, charge=30.0, discharge=20.0, grid=80.0)
    result = lattice.meet([a, b])
    assert np.all(result.solar == 15.0)
    assert np.all(result.reserve == 25.0)
    assert np.all(result.charge == 30.0)
    assert np.all(result.discharge == 20.0)
    assert np.all(result.grid == 80.0)


def test_meet_of_one_tensor_is_itself():
    a = _tensor(solar=12.0)
    result = lattice.meet([a])
    assert np.array_equal(result.solar, a.solar)


def test_meet_infinite_grid_stays_infinite_when_all_uncapped():
    a = _tensor(grid=np.inf)
    b = _tensor(grid=np.inf)
    result = lattice.meet([a, b])
    assert np.all(np.isinf(result.grid))


def test_meet_finite_grid_wins_over_infinite():
    a = _tensor(grid=np.inf)
    b = _tensor(grid=50.0)
    result = lattice.meet([a, b])
    assert np.all(result.grid == 50.0)


def test_meet_rejects_empty_list():
    with pytest.raises(ValueError):
        lattice.meet([])


def test_meet_is_associative_and_order_independent():
    a = _tensor(solar=20.0, reserve=5.0, grid=100.0)
    b = _tensor(solar=15.0, reserve=15.0, grid=80.0)
    c = _tensor(solar=18.0, reserve=10.0, grid=90.0)
    forward = lattice.meet([a, b, c])
    shuffled = lattice.meet([c, a, b])
    for field in ("solar", "reserve", "charge", "discharge", "grid"):
        assert np.array_equal(getattr(forward, field), getattr(shuffled, field))


def test_subsets_containing_anchor_all_include_anchor():
    subsets = list(lattice.subsets_containing_anchor(4, anchor=0))
    assert all(0 in s for s in subsets)
    assert len(subsets) == 2 ** 3  # 3 "other" candidates -> 8 subsets containing the anchor


def test_subsets_containing_anchor_covers_every_combination():
    subsets = set(lattice.subsets_containing_anchor(3, anchor=0))
    expected = {
        frozenset({0}),
        frozenset({0, 1}),
        frozenset({0, 2}),
        frozenset({0, 1, 2}),
    }
    assert subsets == expected


def test_subsets_containing_anchor_yields_increasing_size():
    sizes = [len(s) for s in lattice.subsets_containing_anchor(4, anchor=0)]
    assert sizes == sorted(sizes)


def test_subsets_containing_anchor_supports_nonzero_anchor():
    subsets = list(lattice.subsets_containing_anchor(3, anchor=1))
    assert all(1 in s for s in subsets)


def test_single_candidate_yields_only_the_anchor_singleton():
    subsets = list(lattice.subsets_containing_anchor(1, anchor=0))
    assert subsets == [frozenset({0})]


def test_is_pruned_true_for_superset_of_known_infeasible():
    known = [frozenset({0, 2})]
    assert lattice.is_pruned(frozenset({0, 1, 2}), known)


def test_is_pruned_false_when_not_a_superset_of_any_known():
    known = [frozenset({0, 2})]
    assert not lattice.is_pruned(frozenset({0, 1}), known)


def test_is_pruned_false_with_no_known_infeasible_sets():
    assert not lattice.is_pruned(frozenset({0, 1}), [])


def test_is_pruned_true_for_exact_match():
    known = [frozenset({0, 1})]
    assert lattice.is_pruned(frozenset({0, 1}), known)

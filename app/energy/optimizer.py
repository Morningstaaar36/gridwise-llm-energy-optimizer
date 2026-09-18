"""Signed-flow linear program: the cheapest 24-hour schedule under compiled bounds.

Run off the async event loop when called from the API: the solve is
synchronous and CPU-bound.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import OptimizeResult, linprog

from app.contracts import ConstraintTensor, EnergyRequest, SolveResult

_H = 24
_N = 4 * _H
_G, _S, _B, _E = 0, _H, 2 * _H, 3 * _H


def solve_energy(request: EnergyRequest, tensor: ConstraintTensor) -> SolveResult:
    """Solve for the cheapest grid-import schedule over the 24-hour horizon.

    96 continuous variables, 4 per hour: ``g`` (grid import), ``s`` (solar
    used), ``b`` (signed battery flow: positive charges, negative
    discharges), ``e`` (battery energy after the hour).
    """
    hours_by_index = {entry.hour: entry for entry in request.hours}
    demand = np.array([hours_by_index[h].demand_kwh for h in range(_H)], dtype=np.float64)
    tariff = np.array([hours_by_index[h].tariff_bdt_per_kwh for h in range(_H)], dtype=np.float64)

    capacity = request.battery.capacity_kwh
    initial_energy = request.battery.initial_energy_kwh

    cost = np.zeros(_N, dtype=np.float64)
    cost[_G : _G + _H] = tariff

    # Two equality blocks: hourly energy balance, then battery-state recursion.
    a_eq = np.zeros((2 * _H, _N), dtype=np.float64)
    b_eq = np.zeros(2 * _H, dtype=np.float64)

    for h in range(_H):
        a_eq[h, _G + h] = 1.0
        a_eq[h, _S + h] = 1.0
        a_eq[h, _B + h] = -1.0
        b_eq[h] = demand[h]

    for h in range(_H):
        row = _H + h
        a_eq[row, _E + h] = 1.0
        a_eq[row, _B + h] = -1.0
        if h == 0:
            b_eq[row] = initial_energy
        else:
            a_eq[row, _E + h - 1] = -1.0
            b_eq[row] = 0.0

    bounds: list[tuple[float, float]] = []
    bounds += [(0.0, tensor.grid[h]) for h in range(_H)]
    bounds += [(0.0, tensor.solar[h]) for h in range(_H)]
    # linprog defaults every variable to (0, None); the battery flow's
    # negative lower bound must be set explicitly or discharge is impossible.
    bounds += [(-tensor.discharge[h], tensor.charge[h]) for h in range(_H)]
    bounds += [(tensor.reserve[h], capacity) for h in range(_H)]
    # End-of-day neutrality pins e[23] to the starting energy. Intersect with
    # hour 23's reserve floor rather than replacing it: assigning
    # (initial, initial) outright would silently drop a minimum_battery_reserve
    # directive that covers hour 23. If that floor is above the starting energy
    # the two are genuinely contradictory, and lo > hi makes linprog report
    # infeasibility -- the honest answer -- instead of returning a plan that
    # ignores the directive and only fails later in replay.
    bounds[_E + _H - 1] = (max(tensor.reserve[_H - 1], initial_energy), initial_energy)

    result = linprog(cost, A_eq=a_eq, b_eq=b_eq, bounds=bounds, method="highs")

    if not result.success:
        nan = np.full(_H, np.nan, dtype=np.float64)
        return SolveResult(
            success=False,
            status=result.message,
            cost=float("nan"),
            grid=nan,
            solar=nan,
            flow=nan,
            energy=nan,
            duals=None,
        )

    x = result.x
    return SolveResult(
        success=True,
        status=result.message,
        cost=float(result.fun),
        grid=x[_G : _G + _H],
        solar=x[_S : _S + _H],
        flow=x[_B : _B + _H],
        energy=x[_E : _E + _H],
        duals=_extract_duals(result),
    )


def _extract_duals(result: OptimizeResult) -> dict[str, np.ndarray] | None:
    """Per-hour shadow prices for each constraint family, when HiGHS reports them."""
    eqlin = getattr(result, "eqlin", None)
    lower = getattr(result, "lower", None)
    upper = getattr(result, "upper", None)
    if eqlin is None or lower is None or upper is None:
        return None

    eq_marginals = np.asarray(eqlin.marginals, dtype=np.float64)
    lower_marginals = np.asarray(lower.marginals, dtype=np.float64)
    upper_marginals = np.asarray(upper.marginals, dtype=np.float64)

    return {
        "balance": eq_marginals[0:_H],
        "battery_state": eq_marginals[_H : 2 * _H],
        "grid": upper_marginals[_G : _G + _H],
        "solar": upper_marginals[_S : _S + _H],
        "charge": upper_marginals[_B : _B + _H],
        "discharge": lower_marginals[_B : _B + _H],
        "reserve": lower_marginals[_E : _E + _H],
    }

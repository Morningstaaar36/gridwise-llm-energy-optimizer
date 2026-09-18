"""Rubric-aware selection over the meet-semilattice.

See TASKS.md D3.2 and docs/ARCHITECTURE_CLAMP.md sections 3.5-3.7. Reports
the single most likely interpretation as ``directive_interpretation`` but
schedules against the meet of every plausible reading that is worth
defending, because the two are scored separately and only the latter is
replayed against the organizer's hidden ground truth.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import linprog

from app.config import get_settings
from app.contracts import (
    ConstraintTensor,
    EnergyRequest,
    EnergyResponse,
    ErrorCategory,
    GridWiseError,
    InterpretationSample,
    SolveResult,
    VerificationReport,
)
from app.energy import duals, lattice, response
from app.energy.canonical import canonicalize
from app.energy.optimizer import solve_energy
from app.verification.replay import replay

_SLACK_EPSILON = 1e-9
_H = 24

# Sourced from the shared Settings object rather than a second, parallel
# os.getenv() read: Settings already parses .env correctly (including
# stripping inline "# comment" text, which a bare os.getenv() + int() does
# not) and already defines these two fields with validated bounds. Module
# constants are kept, not inlined at each call site, so
# monkeypatch.setattr(selection, "HEDGE_ENABLED", False) in tests keeps
# working unchanged.
HEDGE_ENABLED = get_settings().hedge_enabled
HEDGE_MAX_CANDIDATES = get_settings().hedge_max_candidates


def _expected_score(coverage: float, nominal_cost: float, candidate_cost: float) -> float:
    """``E(T) = q_T * (25 + 10 * min(1, c_argmax / c_T))`` -- CLAMP #3.5."""
    if candidate_cost <= 0:
        cost_term = 10.0
    else:
        cost_term = 10.0 * min(1.0, nominal_cost / candidate_cost)
    return coverage * (25.0 + cost_term)


def plan_energy(
    request: EnergyRequest, samples: list[InterpretationSample]
) -> tuple[EnergyResponse, VerificationReport]:
    """canonicalize -> hedge over the meet-semilattice -> verify."""
    candidates = canonicalize(request, samples)
    if not candidates:
        raise GridWiseError(
            ErrorCategory.invalid_interpretation, "no candidate interpretation survived"
        )

    argmax = candidates[0]
    nominal = solve_energy(request, argmax.tensor)
    if not nominal.success:
        raise GridWiseError(
            ErrorCategory.infeasible,
            f"the most likely interpretation has no feasible schedule ({nominal.status})",
        )

    reported_directives = argmax.directives
    note_attributions = duals.attribute(request, reported_directives, nominal)

    shipped_tensor = argmax.tensor
    shipped_result = nominal
    best_expected = _expected_score(argmax.posterior, nominal.cost, nominal.cost)

    if HEDGE_ENABLED and len(candidates) > 1:
        num_considered = min(len(candidates), HEDGE_MAX_CANDIDATES)
        infeasible_subsets: list[frozenset[int]] = []
        for subset in lattice.subsets_containing_anchor(num_considered, anchor=0):
            if len(subset) == 1:
                continue  # {0} alone is `nominal`, already the floor
            if lattice.is_pruned(subset, infeasible_subsets):
                continue
            meet_tensor = lattice.meet([candidates[i].tensor for i in subset])
            result = solve_energy(request, meet_tensor)
            if not result.success:
                infeasible_subsets.append(subset)
                continue
            coverage = sum(candidates[i].posterior for i in subset)
            expected = _expected_score(coverage, nominal.cost, result.cost)
            if expected > best_expected:
                best_expected = expected
                shipped_tensor = meet_tensor
                shipped_result = result

    final_result = shipped_result
    if HEDGE_ENABLED:
        final_result = _slack_maximal_resolve(request, shipped_tensor, shipped_result)

    plan = response.build(request, reported_directives, final_result, note_attributions)
    report = replay(request, reported_directives, plan)

    if report.ok:
        return plan, report

    if final_result is not nominal:
        fallback_plan = response.build(request, reported_directives, nominal, note_attributions)
        fallback_report = replay(request, reported_directives, fallback_plan)
        if fallback_report.ok:
            return fallback_plan, fallback_report

    raise GridWiseError(ErrorCategory.replay_failure, "the shipped plan failed independent replay")


def _slack_maximal_resolve(
    request: EnergyRequest, tensor: ConstraintTensor, base_result: SolveResult
) -> SolveResult:
    """Among schedules within `epsilon` of `base_result`'s cost, pick the one
    furthest from every directive-derived bound (CLAMP #3.6). Falls back to
    `base_result` unchanged if the resolve is unexpectedly infeasible --
    mathematically it shouldn't be, since `base_result`'s own solution is
    itself a feasible point of this LP.
    """
    n = 4 * _H + 1  # g, s, b, e, plus one slack scalar t
    g_off, s_off, b_off, e_off, t_off = 0, _H, 2 * _H, 3 * _H, 4 * _H

    hours_by_index = {entry.hour: entry for entry in request.hours}
    demand = np.array([hours_by_index[h].demand_kwh for h in range(_H)], dtype=np.float64)
    tariff = np.array([hours_by_index[h].tariff_bdt_per_kwh for h in range(_H)], dtype=np.float64)
    capacity = request.battery.capacity_kwh
    initial_energy = request.battery.initial_energy_kwh

    cost = np.zeros(n, dtype=np.float64)
    cost[t_off] = -1.0  # maximize t == minimize -t

    a_eq = np.zeros((2 * _H, n), dtype=np.float64)
    b_eq = np.zeros(2 * _H, dtype=np.float64)
    for h in range(_H):
        a_eq[h, g_off + h] = 1.0
        a_eq[h, s_off + h] = 1.0
        a_eq[h, b_off + h] = -1.0
        b_eq[h] = demand[h]
    for h in range(_H):
        row = _H + h
        a_eq[row, e_off + h] = 1.0
        a_eq[row, b_off + h] = -1.0
        if h == 0:
            b_eq[row] = initial_energy
        else:
            a_eq[row, e_off + h - 1] = -1.0
            b_eq[row] = 0.0

    ub_rows: list[np.ndarray] = []
    ub_rhs: list[float] = []

    def add_slack_row(var_index: int, coeff: float, bound_value: float) -> None:
        # coeff * x[var_index] + t <= bound_value, skipped when unbounded (inf).
        if not np.isfinite(bound_value):
            return
        row = np.zeros(n, dtype=np.float64)
        row[var_index] = coeff
        row[t_off] = 1.0
        ub_rows.append(row)
        ub_rhs.append(bound_value)

    for h in range(_H):
        add_slack_row(g_off + h, 1.0, tensor.grid[h])  # t <= grid[h] - g[h]
        add_slack_row(s_off + h, 1.0, tensor.solar[h])  # t <= solar[h] - s[h]
        add_slack_row(b_off + h, 1.0, tensor.charge[h])  # t <= charge[h] - b[h]
        add_slack_row(b_off + h, -1.0, tensor.discharge[h])  # t <= b[h] + discharge[h]
        add_slack_row(e_off + h, -1.0, -tensor.reserve[h])  # t <= e[h] - reserve[h]

    cost_row = np.zeros(n, dtype=np.float64)
    cost_row[g_off : g_off + _H] = tariff
    cost_cap = base_result.cost * (1.0 + _SLACK_EPSILON) if base_result.cost > 0 else _SLACK_EPSILON
    ub_rows.append(cost_row)
    ub_rhs.append(cost_cap)

    bounds: list[tuple[float, float | None]] = []
    bounds += [(0.0, tensor.grid[h]) for h in range(_H)]
    bounds += [(0.0, tensor.solar[h]) for h in range(_H)]
    bounds += [(-tensor.discharge[h], tensor.charge[h]) for h in range(_H)]
    bounds += [(tensor.reserve[h], capacity) for h in range(_H)]
    bounds[e_off + _H - 1] = (initial_energy, initial_energy)
    bounds.append((0.0, None))

    result = linprog(
        cost,
        A_eq=a_eq,
        b_eq=b_eq,
        A_ub=np.array(ub_rows, dtype=np.float64),
        b_ub=np.array(ub_rhs, dtype=np.float64),
        bounds=bounds,
        method="highs",
    )

    if not result.success:
        return base_result

    x = result.x
    grid = x[g_off : g_off + _H]
    return SolveResult(
        success=True,
        status=result.message,
        cost=float(np.dot(tariff, grid)),
        grid=grid,
        solar=x[s_off : s_off + _H],
        flow=x[b_off : b_off + _H],
        energy=x[e_off : e_off + _H],
        duals=base_result.duals,
    )

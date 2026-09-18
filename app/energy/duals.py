"""Dual-certified per-note cost attribution.

See TASKS.md D3.2 and docs/ARCHITECTURE_CLAMP.md section 3.7. HiGHS's shadow
prices give a first-order estimate of a bound's marginal cost with no extra
solve: empirically (see scratch verification), scipy's `linprog` reports
``dual`` such that ``d(cost) ~= dual * d(bound)`` at the solved point, for
both ceiling (upper) and floor (lower) bounds alike. This is an estimate,
not an exact one-directive-lifted re-solve, and restrictions interact --
whatever consumes this must say the numbers do not sum to the total cost.

Scoped to the *reported* interpretation: call this with the directives being
reported as ``directive_interpretation`` and the :class:`SolveResult` from
solving that same interpretation's own tensor (never a hedged/meet result),
so the tensor reconstructed here always matches the one the duals came from.
"""

from __future__ import annotations

import numpy as np

from app.contracts import Directive, DirectiveType, EnergyRequest, SolveResult
from app.energy.compiler import compile_constraints

# directive type -> (ConstraintTensor field it tightens, SolveResult.duals key,
# sign converting that field's value into the actual LP bound the dual is
# measured against; discharge's LP lower bound is the *negative* of the
# tensor's discharge ceiling).
_FAMILY: dict[DirectiveType, tuple[str, str, float]] = {
    DirectiveType.solar_reduction: ("solar", "solar", 1.0),
    DirectiveType.minimum_battery_reserve: ("reserve", "reserve", 1.0),
    DirectiveType.no_charge_window: ("charge", "charge", 1.0),
    DirectiveType.no_discharge_window: ("discharge", "discharge", -1.0),
    DirectiveType.max_grid_window: ("grid", "grid", 1.0),
}


def attribute(
    request: EnergyRequest, directives: list[Directive], result: SolveResult
) -> dict[int, float]:
    """First-order marginal BDT cost per accepted directive, keyed by note_index.

    Holds every other accepted directive fixed and measures this one's own
    contribution to the compiled bounds, weighted by the LP's shadow price.
    Returns ``{}`` when HiGHS did not report duals.
    """
    if result.duals is None:
        return {}

    applied = [d for d in directives if d.directive_type != DirectiveType.no_op]
    if not applied:
        return {}

    full_tensor = compile_constraints(request, applied)

    attributions: dict[int, float] = {}
    for directive in applied:
        family = _FAMILY.get(directive.directive_type)
        if family is None:
            continue
        tensor_field, dual_key, sign = family
        duals = result.duals.get(dual_key)
        if duals is None:
            continue

        without_tensor = compile_constraints(request, [d for d in applied if d is not directive])
        full_values = getattr(full_tensor, tensor_field)
        without_values = getattr(without_tensor, tensor_field)

        contribution = 0.0
        for hour in directive.structured_adjustment.hours:
            full_bound = sign * full_values[hour]
            without_bound = sign * without_values[hour]
            if not (np.isfinite(full_bound) and np.isfinite(without_bound)):
                continue
            contribution += duals[hour] * (full_bound - without_bound)
        attributions[directive.note_index] = contribution

    return attributions

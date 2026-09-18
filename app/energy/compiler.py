"""Compile accepted directives into explicit per-hour constraint bounds.

See TASKS.md D2.1 and docs/ARCHITECTURE_CLAMP.md #2 for the overlapping
solar-reduction composition rule.
"""

from __future__ import annotations

import numpy as np

from app.contracts import ConstraintTensor, Directive, DirectiveType, EnergyRequest


def compile_constraints(request: EnergyRequest, directives: list[Directive]) -> ConstraintTensor:
    """Build a fresh :class:`ConstraintTensor` from immutable request data.

    Each non-``no_op`` directive is applied only to its own listed hours:

    - ``solar_reduction``: ceiling becomes ``min(current, base_solar * factor)``.
      Two solar-reduction directives on the same hour compose by *product*
      (``base * f1 * f2``) rather than ``min`` or last-write-wins: it is the
      tightest reading, and a plan that stays under the product is always
      valid under a looser composition too, since unused solar may be
      curtailed for free.
    - ``minimum_battery_reserve``: floor becomes ``max(current, minimum_energy_kwh)``.
    - ``no_charge_window`` / ``no_discharge_window``: the matching ceiling drops to 0.
    - ``max_grid_window``: ceiling becomes ``min(current, max_grid_kwh)``.
    """
    base_solar_by_hour = {entry.hour: entry.solar_kwh for entry in request.hours}
    base_solar = np.array([base_solar_by_hour[h] for h in range(24)], dtype=np.float64)

    battery = request.battery
    solar = base_solar.copy()
    reserve = np.full(24, battery.minimum_energy_kwh, dtype=np.float64)
    charge = np.full(24, battery.max_charge_kwh_per_hour, dtype=np.float64)
    discharge = np.full(24, battery.max_discharge_kwh_per_hour, dtype=np.float64)
    grid = np.full(24, np.inf, dtype=np.float64)

    for directive in directives:
        directive_type = directive.directive_type
        if directive_type == DirectiveType.no_op:
            continue

        adjustment = directive.structured_adjustment

        if directive_type == DirectiveType.solar_reduction:
            # Multiply the running ceiling, not the base: two directives on the
            # same hour compose by product (base * f1 * f2), the tightest
            # reading. factor is bounded to [0, 1], so this can only tighten
            # the ceiling, never raise it.
            for hour in adjustment.hours:
                solar[hour] *= adjustment.factor
        elif directive_type == DirectiveType.minimum_battery_reserve:
            for hour in adjustment.hours:
                reserve[hour] = max(reserve[hour], adjustment.minimum_energy_kwh)
        elif directive_type == DirectiveType.no_charge_window:
            for hour in adjustment.hours:
                charge[hour] = 0.0
        elif directive_type == DirectiveType.no_discharge_window:
            for hour in adjustment.hours:
                discharge[hour] = 0.0
        elif directive_type == DirectiveType.max_grid_window:
            for hour in adjustment.hours:
                grid[hour] = min(grid[hour], adjustment.max_grid_kwh)

    return ConstraintTensor(
        solar=solar,
        reserve=reserve,
        charge=charge,
        discharge=discharge,
        grid=grid,
    )

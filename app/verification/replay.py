"""Independent replay verifier.

Rebuilds every bound from the raw request and the *reported* directives,
deliberately never by calling app.energy.compiler — see TASKS.md D3.2. This
is a second, independently written implementation of the bound rules, so a
bug in the compiler (or in how the solver or response builder used its
output) is not also invisible here. Walks the plan hour by hour from
``initial_energy_kwh`` using the plan's own recomputed running energy (never
resetting to a reported value), so a single bad hour's error is not silently
absorbed -- it shows up as a violation at every hour downstream too.
"""

from __future__ import annotations

import numpy as np

from app.contracts import (
    Directive,
    DirectiveType,
    EnergyRequest,
    EnergyResponse,
    VerificationReport,
)

_INTERNAL_TOL = 1e-6
_REPORT_TOL = 0.01


def _effective_bounds(
    request: EnergyRequest, directives: list[Directive]
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    hours_by_index = {entry.hour: entry for entry in request.hours}
    solar = np.array([hours_by_index[h].solar_kwh for h in range(24)], dtype=np.float64)

    battery = request.battery
    reserve = np.full(24, battery.minimum_energy_kwh, dtype=np.float64)
    charge = np.full(24, battery.max_charge_kwh_per_hour, dtype=np.float64)
    discharge = np.full(24, battery.max_discharge_kwh_per_hour, dtype=np.float64)
    grid = np.full(24, np.inf, dtype=np.float64)

    for directive in directives:
        if directive.directive_type == DirectiveType.no_op:
            continue
        adjustment = directive.structured_adjustment
        if directive.directive_type == DirectiveType.solar_reduction:
            for hour in adjustment.hours:
                solar[hour] *= adjustment.factor
        elif directive.directive_type == DirectiveType.minimum_battery_reserve:
            for hour in adjustment.hours:
                reserve[hour] = max(reserve[hour], adjustment.minimum_energy_kwh)
        elif directive.directive_type == DirectiveType.no_charge_window:
            for hour in adjustment.hours:
                charge[hour] = 0.0
        elif directive.directive_type == DirectiveType.no_discharge_window:
            for hour in adjustment.hours:
                discharge[hour] = 0.0
        elif directive.directive_type == DirectiveType.max_grid_window:
            for hour in adjustment.hours:
                grid[hour] = min(grid[hour], adjustment.max_grid_kwh)

    return solar, reserve, charge, discharge, grid


def replay(
    request: EnergyRequest,
    reported_directives: list[Directive],
    response: EnergyResponse,
) -> VerificationReport:
    """Independently verify a response against the raw request and directives."""
    solar_cap, reserve_floor, charge_cap, discharge_cap, grid_cap = _effective_bounds(
        request, reported_directives
    )
    hours_by_index = {entry.hour: entry for entry in request.hours}
    capacity = request.battery.capacity_kwh
    initial_energy = request.battery.initial_energy_kwh

    violations: list[str] = []
    max_residual = 0.0
    energy = initial_energy

    recomputed_total_grid = 0.0
    recomputed_total_cost = 0.0
    recomputed_peak_grid = 0.0

    for hour in range(24):
        entry = response.hourly_plan[hour]
        demand = hours_by_index[hour].demand_kwh
        tariff = hours_by_index[hour].tariff_bdt_per_kwh

        grid_kwh = entry.grid_kwh
        solar_used = entry.solar_used_kwh
        magnitude = entry.battery_kwh

        if entry.battery_action == "charge":
            charge_flow, discharge_flow = magnitude, 0.0
        elif entry.battery_action == "discharge":
            charge_flow, discharge_flow = 0.0, magnitude
        else:
            charge_flow, discharge_flow = 0.0, 0.0
            if abs(magnitude) > _INTERNAL_TOL:
                violations.append(f"h{hour}: idle action with nonzero magnitude {magnitude:.6f}")

        balance = grid_kwh + solar_used + discharge_flow - charge_flow
        balance_residual = abs(balance - demand)
        max_residual = max(max_residual, balance_residual)
        if balance_residual > _REPORT_TOL:
            violations.append(f"h{hour}: balance {balance:.4f} != demand {demand:.4f}")

        if charge_flow > charge_cap[hour] + _REPORT_TOL:
            violations.append(f"h{hour}: charge-rate {charge_flow:.4f} > {charge_cap[hour]:.4f}")
        if discharge_flow > discharge_cap[hour] + _REPORT_TOL:
            violations.append(
                f"h{hour}: discharge-rate {discharge_flow:.4f} > {discharge_cap[hour]:.4f}"
            )
        if solar_used > solar_cap[hour] + _REPORT_TOL:
            violations.append(f"h{hour}: solar-used {solar_used:.4f} > cap {solar_cap[hour]:.4f}")
        if grid_kwh > grid_cap[hour] + _REPORT_TOL:
            violations.append(f"h{hour}: grid-cap {grid_kwh:.4f} > {grid_cap[hour]:.4f}")

        energy = energy + charge_flow - discharge_flow
        state_residual = abs(energy - entry.battery_energy_after_kwh)
        max_residual = max(max_residual, state_residual)
        if state_residual > _REPORT_TOL:
            violations.append(
                f"h{hour}: battery-state reported {entry.battery_energy_after_kwh:.4f} "
                f"!= recomputed {energy:.4f}"
            )

        if energy < reserve_floor[hour] - _REPORT_TOL:
            violations.append(f"h{hour}: reserve {energy:.4f} < floor {reserve_floor[hour]:.4f}")
        if energy > capacity + _REPORT_TOL:
            violations.append(f"h{hour}: energy {energy:.4f} > capacity {capacity:.4f}")

        recomputed_total_grid += grid_kwh
        recomputed_total_cost += grid_kwh * tariff
        recomputed_peak_grid = max(recomputed_peak_grid, grid_kwh)

    neutrality_residual = abs(energy - initial_energy)
    max_residual = max(max_residual, neutrality_residual)
    if neutrality_residual > _REPORT_TOL:
        violations.append(f"end-of-day neutrality: {energy:.4f} != initial {initial_energy:.4f}")

    for label, recomputed, reported in (
        ("total_grid_kwh", recomputed_total_grid, response.total_grid_kwh),
        ("total_cost_bdt", recomputed_total_cost, response.total_cost_bdt),
        ("peak_grid_kwh", recomputed_peak_grid, response.peak_grid_kwh),
    ):
        residual = abs(recomputed - reported)
        max_residual = max(max_residual, residual)
        if residual > _REPORT_TOL:
            violations.append(f"{label} reported {reported:.4f} != recomputed {recomputed:.4f}")

    return VerificationReport(ok=not violations, violations=violations, max_residual=max_residual)

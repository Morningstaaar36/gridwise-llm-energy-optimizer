"""Convert a solved LP into the outbound EnergyResponse.

Totals are recomputed from the exact values being
serialized rather than reused from the solver's own objective, so a
normalization bug can never silently disagree with the numbers a judge sees.
"""

from __future__ import annotations

from app.contracts import (
    Directive,
    DirectiveType,
    EnergyRequest,
    EnergyResponse,
    HourPlan,
    SolveResult,
)

_IDLE_THRESHOLD = 1e-8
_NOISE_TOLERANCE = 1e-9


def build(
    request: EnergyRequest,
    directives: list[Directive],
    result: SolveResult,
    note_attributions: dict[int, float] | None = None,
) -> EnergyResponse:
    """Build the outbound response from a successful :class:`SolveResult`."""
    hourly_plan = [_hour_plan(hour, result) for hour in range(24)]

    total_grid_kwh = sum(entry.grid_kwh for entry in hourly_plan)
    tariff_by_hour = {entry.hour: entry.tariff_bdt_per_kwh for entry in request.hours}
    total_cost_bdt = sum(entry.grid_kwh * tariff_by_hour[entry.hour] for entry in hourly_plan)
    peak_grid_kwh = max(entry.grid_kwh for entry in hourly_plan)

    plan_summary = _summarize(
        directives, hourly_plan, total_grid_kwh, total_cost_bdt, peak_grid_kwh, note_attributions
    )

    return EnergyResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=directives,
        hourly_plan=hourly_plan,
        total_grid_kwh=total_grid_kwh,
        total_cost_bdt=total_cost_bdt,
        peak_grid_kwh=peak_grid_kwh,
        plan_summary=plan_summary,
    )


def _hour_plan(hour: int, result: SolveResult) -> HourPlan:
    flow = float(result.flow[hour])
    if flow > _IDLE_THRESHOLD:
        action, magnitude = "charge", flow
    elif flow < -_IDLE_THRESHOLD:
        action, magnitude = "discharge", -flow
    else:
        action, magnitude = "idle", 0.0

    return HourPlan(
        hour=hour,
        grid_kwh=_snap_to_zero(float(result.grid[hour])),
        solar_used_kwh=_snap_to_zero(float(result.solar[hour])),
        battery_action=action,
        battery_kwh=magnitude,
        battery_energy_after_kwh=_snap_to_zero(float(result.energy[hour])),
    )


def _snap_to_zero(value: float) -> float:
    """Clear floating-point noise just below zero without concealing a real
    violation: pydantic's ``ge=0`` still rejects anything beyond the noise
    band, so a genuine bug still fails loud instead of being clipped away."""
    return 0.0 if -_NOISE_TOLERANCE <= value < 0.0 else value


def _summarize(
    directives: list[Directive],
    hourly_plan: list[HourPlan],
    total_grid_kwh: float,
    total_cost_bdt: float,
    peak_grid_kwh: float,
    note_attributions: dict[int, float] | None,
) -> str:
    applied = [d for d in directives if d.directive_type != DirectiveType.no_op]
    if applied:
        clauses = ", ".join(f"note {d.note_index} ({d.directive_type.value})" for d in applied)
        directive_sentence = f"Applied restrictions: {clauses}."
    else:
        directive_sentence = "No operator note changed today's schedule."

    totals_sentence = (
        f"Total grid import is {total_grid_kwh:.2f} kWh at a cost of {total_cost_bdt:.2f} BDT, "
        f"with a peak hourly import of {peak_grid_kwh:.2f} kWh."
    )

    final_energy = hourly_plan[-1].battery_energy_after_kwh
    neutrality_sentence = (
        f"Battery energy is restored to {final_energy:.2f} kWh by the end of hour 23."
    )

    sentences = [directive_sentence, totals_sentence, neutrality_sentence]

    if note_attributions:
        clauses = ", ".join(
            f"note {note_index} ~{cost:.2f} BDT"
            for note_index, cost in sorted(note_attributions.items())
        )
        sentences.append(
            f"Estimated marginal cost per restriction, holding the others fixed: {clauses}. "
            "Restrictions interact, so these estimates do not sum to the total cost."
        )

    return " ".join(sentences)

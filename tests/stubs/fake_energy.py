"""Stand-in for the energy half, owned by the language/API branch.

Lets the API, pipeline, and error paths be built and tested before
``feat/energy-verify`` merges. Development only: Gate 4 (B4.2) replaces the
import in ``app/pipeline.py`` with the real selector, and no reference to this
module may survive under ``app/``.
"""

from __future__ import annotations

import json
import pathlib

from app.contracts import (
    EnergyRequest,
    ErrorCategory,
    EnergyResponse,
    GridWiseError,
    InterpretationSample,
    VerificationReport,
)

_PLAN = json.loads(
    (pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "stub_plan.json").read_text()
)


def plan_energy(
    request: EnergyRequest, samples: list[InterpretationSample]
) -> tuple[EnergyResponse, VerificationReport]:
    """Canned valid plan, echoing the real scenario_id and reported directives."""
    reported = samples[0].directives if samples else []
    response = EnergyResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=reported,
        hourly_plan=_PLAN["hourly_plan"],
        total_grid_kwh=_PLAN["total_grid_kwh"],
        total_cost_bdt=_PLAN["total_cost_bdt"],
        peak_grid_kwh=_PLAN["peak_grid_kwh"],
        plan_summary="Stub plan for development; not a real optimisation.",
    )
    return response, VerificationReport(ok=True, violations=[], max_residual=0.0)


def plan_energy_failing(
    request: EnergyRequest, samples: list[InterpretationSample]
) -> tuple[EnergyResponse, VerificationReport]:
    """Exercises the controlled-500 path when replay rejects a schedule."""
    raise GridWiseError(ErrorCategory.replay_failure, "replay rejected the candidate schedule")

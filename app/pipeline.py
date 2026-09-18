"""Request orchestration under a hard deadline.

The whole integration between the two development branches is the two calls
below: interpretation produces samples, the energy half turns samples into a
verified plan. Everything else on either side is private to its branch.
"""

from __future__ import annotations

import asyncio
import time

from app.config import Settings
from app.contracts import EnergyRequest, EnergyResponse, ErrorCategory, GridWiseError
from app.energy.selection import plan_energy
from app.interpretation.ensemble import interpret_notes
from app.interpretation.provider import LLMProvider
from app.observability import RequestTrace, get_logger

logger = get_logger(__name__)


async def run(
    request: EnergyRequest, settings: Settings, provider: LLMProvider
) -> tuple[EnergyResponse, RequestTrace]:
    trace = RequestTrace(scenario_id=request.scenario_id)
    deadline = time.monotonic() + settings.request_deadline_seconds

    with trace.stage("interpret"):
        samples = await interpret_notes(request, settings, provider, trace, deadline)

    if time.monotonic() >= deadline:
        raise GridWiseError(
            ErrorCategory.deadline_exceeded, "request deadline reached before scheduling"
        )

    # The solver is synchronous and CPU-bound; keep it off the event loop so
    # concurrent requests are not serialised behind it.
    with trace.stage("plan"):
        response, report = await asyncio.to_thread(plan_energy, request, samples)

    if not report.ok:
        logger.error("replay rejected plan: %d violation(s)", len(report.violations))
        raise GridWiseError(
            ErrorCategory.replay_failure, "internal verification rejected the schedule"
        )

    logger.info("completed %s", trace.as_dict())
    return response, trace

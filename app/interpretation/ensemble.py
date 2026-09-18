"""K-sample interpretation with a bounded repair round.

A single greedy sample gives the model's *preferred* reading and no signal about
whether that reading is contested — which is exactly the signal the downstream
hedge needs, because hidden operator notes are paraphrases and paraphrase is
ambiguity. So we draw K samples in one round-trip and let the energy half decide
what to do when they disagree.

Samples are validated independently and invalid ones are dropped, not repaired:
a malformed sample is evidence about that sample only, and the surviving ones
still carry a usable distribution. The repair round fires only when *nothing*
survives.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from app.config import Settings
from app.contracts import (
    EnergyRequest,
    ErrorCategory,
    GridWiseError,
    InterpretationSample,
)
from app.interpretation import prompts
from app.interpretation.guardrails import validate
from app.interpretation.provider import LLMProvider
from app.observability import RequestTrace, get_logger

logger = get_logger(__name__)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_json(text: str) -> Any:
    """Tolerate markdown fences and leading prose around the JSON object."""
    candidate = text.strip()
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise GridWiseError(ErrorCategory.invalid_interpretation, "model output was not valid JSON")


def _validate_batch(
    request: EnergyRequest, texts: list[str]
) -> tuple[list[InterpretationSample], list[str]]:
    samples: list[InterpretationSample] = []
    reasons: list[str] = []
    for text in texts:
        try:
            samples.append(
                InterpretationSample(directives=validate(request, parse_json(text)), weight=1.0)
            )
        except GridWiseError as exc:
            reasons.append(exc.message)
    return samples, reasons


def _repair_suffix(reasons: list[str]) -> str:
    unique: list[str] = []
    for reason in reasons:
        if reason not in unique:
            unique.append(reason)
    listed = "\n".join(f"- {reason}" for reason in unique[:6])
    return (
        "\n\nYour previous response was rejected by deterministic validation:\n"
        f"{listed}\n\n"
        "Return corrected JSON. Do not guess values you cannot justify from the "
        "note text; if a note states no supported rule, classify it as no_op."
    )


async def interpret_notes(
    request: EnergyRequest,
    settings: Settings,
    provider: LLMProvider,
    trace: RequestTrace | None = None,
    deadline: float | None = None,
) -> list[InterpretationSample]:
    """Return every sample that survived validation. Never returns an empty list."""
    trace = trace or RequestTrace()
    deadline = deadline or (time.monotonic() + settings.request_deadline_seconds)
    prompt = prompts.build(request)

    attempts_left = settings.llm_max_attempts
    reasons: list[str] = []

    while attempts_left > 0:
        if time.monotonic() >= deadline:
            raise GridWiseError(
                ErrorCategory.deadline_exceeded, "request deadline reached during interpretation"
            )
        attempts_left -= 1

        remaining = deadline - time.monotonic()
        try:
            result = await asyncio.wait_for(
                provider.complete(prompt, settings.llm_samples), timeout=remaining
            )
        except TimeoutError:
            raise GridWiseError(
                ErrorCategory.deadline_exceeded, "request deadline reached waiting for the model"
            ) from None
        trace.model_calls += result.calls

        samples, batch_reasons = _validate_batch(request, result.texts)
        trace.samples_accepted += len(samples)
        trace.samples_rejected += len(batch_reasons)

        if samples:
            logger.info(
                "interpretation accepted=%d rejected=%d calls=%d",
                len(samples),
                len(batch_reasons),
                result.calls,
            )
            return samples

        reasons = batch_reasons
        if attempts_left > 0:
            # Re-ask once with the concrete validation failures appended.
            prompt = prompts.RenderedPrompt(
                system=prompt.system,
                user=prompt.user + _repair_suffix(reasons),
                delimiter=prompt.delimiter,
                version=prompt.version,
            )

    raise GridWiseError(
        ErrorCategory.invalid_interpretation,
        "model output failed validation after repair (" + "; ".join(reasons[:3]) + ")",
    )

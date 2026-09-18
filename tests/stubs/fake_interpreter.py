"""Stand-in for ``app.interpretation.ensemble.interpret_notes``.

Development/test fixture only. Never imported from ``app/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.contracts import InterpretationSample

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
_STUB_INTERPRETATION = json.loads((_FIXTURES / "stub_interpretation.json").read_text())
_STUB_LLM_SAMPLES = json.loads((_FIXTURES / "stub_llm_samples.json").read_text())


def _sample(directives: list[dict[str, Any]], weight: float = 1.0) -> InterpretationSample:
    return InterpretationSample(directives=directives, weight=weight)


def ground_truth_samples(scenario_id: str) -> InterpretationSample:
    """One sample built from the ground-truth directives for ``scenario_id``."""
    return _sample(_STUB_INTERPRETATION[scenario_id])


def disagreeing_samples() -> list[InterpretationSample]:
    """Five samples for SAMPLE-01 with engineered disagreement.

    3 of 5 (indexes 0, 1, 3) compile to the same tensor, 1 (index 2) has a
    wider hour window, and 1 (index 4) has the factor flipped. Expected CS3
    result: 3 classes with posterior {0.6, 0.2, 0.2}.
    """
    return [
        _sample(entry["raw"]["directive_interpretation"])
        for entry in _STUB_LLM_SAMPLES["samples"]
    ]

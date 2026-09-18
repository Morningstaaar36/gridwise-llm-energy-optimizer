"""CS3 — Constraint-Space Self-Consistency: cluster ensemble samples by meaning.

See TASKS.md D3.1 and docs/ARCHITECTURE_CLAMP.md section 3.3. Two samples mean
the same thing iff they compile to the same tensor, so clustering happens in
executable constraint space rather than by approximate text similarity.
"""

from __future__ import annotations

import numpy as np

from app.contracts import Candidate, ConstraintTensor, EnergyRequest, InterpretationSample
from app.energy.compiler import compile_constraints

_FIELDS = ("solar", "reserve", "charge", "discharge", "grid")


def _tensors_match(a: ConstraintTensor, b: ConstraintTensor) -> bool:
    return all(
        np.array_equal(np.round(getattr(a, field), 9), np.round(getattr(b, field), 9))
        for field in _FIELDS
    )


def canonicalize(request: EnergyRequest, samples: list[InterpretationSample]) -> list[Candidate]:
    """Compile every sample, cluster by exact tensor equality, score by posterior.

    Two textually different samples that compile to the same tensor are one
    class: this is what makes a `no_charge_window` on an hour where charging
    was already impossible cost nothing, and what collapses formatting noise
    like `factor: 0.2` vs `0.20`.

    Posterior blends normalized cluster frequency with each cluster's mean
    sample weight via a stabilized softmax (`freq * exp(mean_weight - max)`,
    renormalized). When every sample carries the default weight of 1.0 (no
    provider confidence signal), the exponential term is identical across
    every cluster and cancels in the renormalization, so the result reduces
    exactly to plain frequency.
    """
    if not samples:
        raise ValueError("canonicalize requires at least one sample")

    tensors = [compile_constraints(request, sample.directives) for sample in samples]

    cluster_tensors: list[ConstraintTensor] = []
    cluster_members: list[list[int]] = []
    for index, tensor in enumerate(tensors):
        for cluster_index, representative in enumerate(cluster_tensors):
            if _tensors_match(tensor, representative):
                cluster_members[cluster_index].append(index)
                break
        else:
            cluster_tensors.append(tensor)
            cluster_members.append([index])

    total_samples = len(samples)
    frequencies = np.array([len(members) / total_samples for members in cluster_members])
    mean_weights = np.array(
        [np.mean([samples[i].weight for i in members]) for members in cluster_members]
    )

    stabilized = mean_weights - mean_weights.max()
    raw_scores = frequencies * np.exp(stabilized)
    posteriors = raw_scores / raw_scores.sum()

    candidates = [
        Candidate(
            tensor=cluster_tensors[cluster_index],
            posterior=float(posteriors[cluster_index]),
            directives=samples[cluster_members[cluster_index][0]].directives,
        )
        for cluster_index in range(len(cluster_tensors))
    ]
    candidates.sort(key=lambda candidate: candidate.posterior, reverse=True)
    return candidates

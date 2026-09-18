"""Shared GridWise boundary types for the API, interpretation, and energy modules.

Keep this module free of imports from other ``app`` modules. Both development
branches depend on these names and the public wire format they define.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

import numpy as np
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)


class DirectiveType(StrEnum):
    solar_reduction = "solar_reduction"
    minimum_battery_reserve = "minimum_battery_reserve"
    no_charge_window = "no_charge_window"
    no_discharge_window = "no_discharge_window"
    max_grid_window = "max_grid_window"
    no_op = "no_op"


class ErrorCategory(StrEnum):
    invalid_request = "invalid_request"
    invalid_interpretation = "invalid_interpretation"
    provider_failure = "provider_failure"
    infeasible = "infeasible"
    solver_failure = "solver_failure"
    replay_failure = "replay_failure"
    deadline_exceeded = "deadline_exceeded"


class WireModel(BaseModel):
    """Reject unknown public fields instead of silently ignoring them."""

    model_config = ConfigDict(extra="forbid", strict=True)


class HourEntry(WireModel):
    hour: StrictInt = Field(ge=0, le=23)
    demand_kwh: float = Field(ge=0, allow_inf_nan=False)
    solar_kwh: float = Field(ge=0, allow_inf_nan=False)
    tariff_bdt_per_kwh: float = Field(allow_inf_nan=False)


class Battery(WireModel):
    capacity_kwh: float = Field(ge=0, allow_inf_nan=False)
    initial_energy_kwh: float = Field(ge=0, allow_inf_nan=False)
    minimum_energy_kwh: float = Field(ge=0, allow_inf_nan=False)
    max_charge_kwh_per_hour: float = Field(ge=0, allow_inf_nan=False)
    max_discharge_kwh_per_hour: float = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def check_energy_bounds(self) -> Battery:
        if not self.minimum_energy_kwh <= self.initial_energy_kwh <= self.capacity_kwh:
            raise ValueError("battery minimum, initial energy, and capacity are inconsistent")
        return self


class EnergyRequest(WireModel):
    scenario_id: str = Field(min_length=1)
    operator_notes: list[str] = Field(min_length=1, max_length=3)
    hours: list[HourEntry] = Field(min_length=24, max_length=24)
    battery: Battery

    @field_validator("scenario_id")
    @classmethod
    def scenario_id_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("scenario_id must not be blank")
        return value

    @field_validator("operator_notes")
    @classmethod
    def notes_not_blank(cls, value: list[str]) -> list[str]:
        if any(not note.strip() for note in value):
            raise ValueError("operator notes must not be blank")
        return value

    @field_validator("hours")
    @classmethod
    def hours_cover_day(cls, value: list[HourEntry]) -> list[HourEntry]:
        if {entry.hour for entry in value} != set(range(24)):
            raise ValueError("hours must contain each integer from 0 through 23 exactly once")
        return value


class HourAdjustment(WireModel):
    hours: list[StrictInt] = Field(min_length=1, max_length=24)

    @field_validator("hours")
    @classmethod
    def hours_are_ascending_and_unique(cls, value: list[int]) -> list[int]:
        if any(hour < 0 or hour > 23 for hour in value):
            raise ValueError("directive hours must be between 0 and 23")
        if value != sorted(set(value)):
            raise ValueError("directive hours must be unique and ascending")
        return value


class SolarReductionAdj(HourAdjustment):
    factor: float = Field(ge=0, le=1, allow_inf_nan=False)


class MinReserveAdj(HourAdjustment):
    minimum_energy_kwh: float = Field(ge=0, allow_inf_nan=False)


class NoChargeAdj(HourAdjustment):
    pass


class NoDischargeAdj(HourAdjustment):
    pass


class MaxGridAdj(HourAdjustment):
    max_grid_kwh: float = Field(ge=0, allow_inf_nan=False)


class DirectiveBase(WireModel):
    note_index: StrictInt = Field(ge=0)
    explanation: str = Field(min_length=1, max_length=300)

    @field_validator("explanation")
    @classmethod
    def explanation_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("explanation must not be blank")
        return value


class SolarReductionDirective(DirectiveBase):
    applies: Literal[True]
    directive_type: Literal[DirectiveType.solar_reduction]
    structured_adjustment: SolarReductionAdj


class MinReserveDirective(DirectiveBase):
    applies: Literal[True]
    directive_type: Literal[DirectiveType.minimum_battery_reserve]
    structured_adjustment: MinReserveAdj


class NoChargeDirective(DirectiveBase):
    applies: Literal[True]
    directive_type: Literal[DirectiveType.no_charge_window]
    structured_adjustment: NoChargeAdj


class NoDischargeDirective(DirectiveBase):
    applies: Literal[True]
    directive_type: Literal[DirectiveType.no_discharge_window]
    structured_adjustment: NoDischargeAdj


class MaxGridDirective(DirectiveBase):
    applies: Literal[True]
    directive_type: Literal[DirectiveType.max_grid_window]
    structured_adjustment: MaxGridAdj


class NoOpDirective(DirectiveBase):
    applies: Literal[False]
    directive_type: Literal[DirectiveType.no_op]
    structured_adjustment: None


Directive = Annotated[
    SolarReductionDirective
    | MinReserveDirective
    | NoChargeDirective
    | NoDischargeDirective
    | MaxGridDirective
    | NoOpDirective,
    Field(discriminator="directive_type"),
]


class InterpretationSample(WireModel):
    directives: list[Directive] = Field(min_length=1, max_length=3)
    # Providers may supply negative mean token log probabilities. The energy
    # selector is responsible for normalizing these into nonnegative posteriors.
    weight: float = Field(default=1.0, allow_inf_nan=False)

    @field_validator("directives")
    @classmethod
    def directive_indexes_are_contiguous(cls, value: list[Directive]) -> list[Directive]:
        if [directive.note_index for directive in value] != list(range(len(value))):
            raise ValueError("directive indexes must be unique and in note order")
        return value


@dataclass
class ConstraintTensor:
    solar: np.ndarray
    reserve: np.ndarray
    charge: np.ndarray
    discharge: np.ndarray
    grid: np.ndarray

    def __post_init__(self) -> None:
        for name in ("solar", "reserve", "charge", "discharge", "grid"):
            values = getattr(self, name)
            if not isinstance(values, np.ndarray) or values.shape != (24,):
                raise ValueError(f"{name} must be a 24-element NumPy array")
            if values.dtype != np.dtype("float64"):
                raise ValueError(f"{name} must have float64 dtype")
            if np.isnan(values).any() or np.isneginf(values).any() or (values < 0).any():
                raise ValueError(f"{name} contains invalid bounds")
            if name != "grid" and not np.isfinite(values).all():
                raise ValueError(f"{name} must contain finite bounds")


@dataclass
class Candidate:
    tensor: ConstraintTensor
    posterior: float
    directives: list[Directive]


@dataclass
class SolveResult:
    success: bool
    status: str
    cost: float
    grid: np.ndarray
    solar: np.ndarray
    flow: np.ndarray
    energy: np.ndarray
    duals: dict[str, np.ndarray] | None = None


@dataclass
class VerificationReport:
    ok: bool
    violations: list[str]
    max_residual: float


class HourPlan(WireModel):
    hour: StrictInt = Field(ge=0, le=23)
    grid_kwh: float = Field(ge=0, allow_inf_nan=False)
    solar_used_kwh: float = Field(ge=0, allow_inf_nan=False)
    battery_action: Literal["charge", "discharge", "idle"]
    battery_kwh: float = Field(ge=0, allow_inf_nan=False)
    battery_energy_after_kwh: float = Field(ge=0, allow_inf_nan=False)


class EnergyResponse(WireModel):
    scenario_id: str = Field(min_length=1)
    directive_interpretation: list[Directive] = Field(min_length=1, max_length=3)
    hourly_plan: list[HourPlan] = Field(min_length=24, max_length=24)
    total_grid_kwh: float = Field(ge=0, allow_inf_nan=False)
    total_cost_bdt: float = Field(allow_inf_nan=False)
    peak_grid_kwh: float = Field(ge=0, allow_inf_nan=False)
    plan_summary: str = Field(min_length=1)

    @field_validator("directive_interpretation")
    @classmethod
    def response_indexes_are_contiguous(cls, value: list[Directive]) -> list[Directive]:
        if [directive.note_index for directive in value] != list(range(len(value))):
            raise ValueError("directive indexes must be unique and in note order")
        return value

    @field_validator("hourly_plan")
    @classmethod
    def plan_covers_day(cls, value: list[HourPlan]) -> list[HourPlan]:
        if [entry.hour for entry in value] != list(range(24)):
            raise ValueError("hourly plan must contain hours 0 through 23 in order")
        return value

    @field_validator("plan_summary")
    @classmethod
    def summary_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("plan_summary must not be blank")
        return value


class GridWiseError(Exception):
    """Categorized failure with an operator-safe message."""

    def __init__(self, category: ErrorCategory, message: str) -> None:
        self.category = category
        self.message = message
        super().__init__(message)

"""Scenario simulation API contracts."""
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.api.schemas import FacilityType


class ScenarioRunRequest(BaseModel):
    scenario_type: Literal["baseline", "optimized", "future_demand"]
    input_data_status: Literal["official", "estimated", "synthetic_demo"] = "estimated"
    label: str = Field(min_length=1, max_length=120)
    group_id: str | None = None
    facility_type: FacilityType = "collection_centre"
    demand_by_ward: dict[str, float]
    fixed_costs: dict[str, float]
    capacities: dict[str, float]
    budget: float | None = Field(default=None, ge=0)
    max_facilities: int = Field(default=5, ge=0, le=20)
    transport_cost_per_tonne_km: float = Field(default=1.0, ge=0)
    unserved_penalty_per_tonne: float = Field(default=1_000_000, ge=0)
    future_growth_percent: float = Field(default=0, ge=-100, le=1000)
    baseline_facility_ids: list[str] | None = None
    criteria_weights: dict[str, float] | None = None
    required_fields: dict[str, Any] = Field(default_factory=lambda: {"hard_allowed": True})
    constraint_types: list[str] = Field(default_factory=list)
    constraint_buffer_m: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def valid_baseline(self):
        if self.scenario_type == "baseline" and self.baseline_facility_ids is None:
            raise ValueError("baseline_facility_ids is required for a baseline scenario")
        return self


class ScenarioRunResponse(BaseModel):
    run_id: str
    group_id: str
    created_at: str
    dataset_version: str
    parameters: dict[str, Any]
    criteria_weights: dict[str, float]
    results: dict[str, Any]


class ScenarioComparisonRequest(BaseModel):
    run_ids: list[str] = Field(min_length=2, max_length=10)

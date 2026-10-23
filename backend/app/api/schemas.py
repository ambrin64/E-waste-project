"""OpenAPI request and response models for spatial data and suitability."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

FacilityType = Literal["collection_centre", "dismantling_facility"]


class SuitabilityRequest(BaseModel):
    facility_type: FacilityType = "collection_centre"
    weights: dict[str, float] | None = None
    pairwise_matrix: list[list[float]] | None = None
    required_fields: dict[str, Any] = Field(default_factory=dict)
    constraint_types: list[str] = Field(default_factory=list)
    constraint_buffer_m: float = Field(default=0, ge=0, description="User-configured buffer in metres")

    @model_validator(mode="after")
    def only_one_weight_source(self):
        if self.weights is not None and self.pairwise_matrix is not None:
            raise ValueError("Provide either weights or pairwise_matrix")
        return self


class ErrorResponse(BaseModel):
    code: str
    detail: str


class AHPResponse(BaseModel):
    criteria: list[str]
    weights: dict[str, float]
    lambda_max: float
    consistency_index: float
    consistency_ratio: float
    consistency_acceptable: bool


class SuitabilityResponse(BaseModel):
    facility_type: FacilityType
    model_version: str
    data_status: str
    criteria_directions: dict[str, str]
    weights: dict[str, float]
    ahp: AHPResponse | None
    assumptions: list[str]
    validation: list[dict[str, Any]]
    geojson: dict[str, Any]

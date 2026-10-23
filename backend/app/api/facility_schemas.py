"""Facility design API request contract."""
from pydantic import BaseModel, Field


class FacilityDesignRequest(BaseModel):
    daily_throughput_tonnes_per_day: float = Field(gt=0, le=100000)
    operating_days_per_year: int = Field(ge=1, le=366)
    storage_duration_days: float = Field(ge=0, le=3650)
    plot_width_m: float = Field(gt=0, le=10000)
    plot_depth_m: float = Field(gt=0, le=10000)
    receiving_area_m2_per_tpd: float = Field(default=0.8, ge=0)
    inspection_area_m2_per_tpd: float = Field(default=0.5, ge=0)
    dismantling_area_m2_per_tpd: float = Field(default=3.0, ge=0)
    storage_area_m2_per_stored_tonne: float = Field(default=2.5, ge=0)
    dispatch_area_m2_per_tpd: float = Field(default=0.7, ge=0)
    circulation_fraction: float = Field(default=0.25, ge=0, le=5)

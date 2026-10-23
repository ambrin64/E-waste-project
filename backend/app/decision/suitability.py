"""AHP and explainable, criterion-normalized candidate scoring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import geopandas as gpd
import numpy as np
import pandas as pd

FacilityType = Literal["collection_centre", "dismantling_facility"]
CRS_METRIC = "EPSG:32643"  # UTM zone 43N; metric calculations only.
RANDOM_INDEX = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24,
                7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}


@dataclass(frozen=True)
class Criterion:
    name: str
    field: str
    direction: Literal["benefit", "cost"]


CRITERIA: dict[FacilityType, tuple[Criterion, ...]] = {
    "collection_centre": (
        Criterion("demand_access", "demand_access", "benefit"),
        Criterion("road_access", "road_access", "benefit"),
        Criterion("land_cost", "land_cost", "cost"),
        Criterion("environmental_risk", "environmental_risk", "cost"),
    ),
    "dismantling_facility": (
        Criterion("industrial_compatibility", "industrial_compatibility", "benefit"),
        Criterion("road_access", "road_access", "benefit"),
        Criterion("land_cost", "land_cost", "cost"),
        Criterion("environmental_risk", "environmental_risk", "cost"),
    ),
}


@dataclass
class AHPResult:
    criteria: list[str]
    weights: dict[str, float]
    lambda_max: float
    consistency_index: float
    consistency_ratio: float
    consistency_acceptable: bool


def ahp_weights(criteria: list[str], pairwise_matrix: list[list[float]]) -> AHPResult:
    """Calculate principal-eigenvector weights and Saaty consistency ratio."""
    matrix = np.asarray(pairwise_matrix, dtype=float)
    n = len(criteria)
    if n < 1 or matrix.shape != (n, n):
        raise ValueError("Pairwise matrix dimensions must match a non-empty criteria list")
    if not np.isfinite(matrix).all() or np.any(matrix <= 0):
        raise ValueError("Pairwise values must be finite and positive")
    if not np.allclose(np.diag(matrix), 1.0) or not np.allclose(matrix * matrix.T, 1.0, atol=1e-8):
        raise ValueError("Pairwise matrix must be reciprocal with a unit diagonal")
    eigenvalues, eigenvectors = np.linalg.eig(matrix)
    position = int(np.argmax(eigenvalues.real))
    vector = np.abs(eigenvectors[:, position].real)
    weights = vector / vector.sum()
    lambda_max = float(eigenvalues[position].real)
    ci = max(0.0, (lambda_max - n) / (n - 1)) if n > 1 else 0.0
    ri = RANDOM_INDEX.get(n, 1.49)
    cr = ci / ri if ri else 0.0
    return AHPResult(criteria, dict(zip(criteria, weights.tolist())), lambda_max, ci, cr, cr <= 0.1)


def normalize_criterion(values: pd.Series, direction: Literal["benefit", "cost"]) -> pd.Series:
    """Min-max scale to 0 to 100; reverse cost criteria; constants score equally at 100."""
    numeric = pd.to_numeric(values, errors="coerce")
    if numeric.isna().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("Criterion values must be finite numeric values")
    lo, hi = float(numeric.min()), float(numeric.max())
    if np.isclose(lo, hi):
        return pd.Series(100.0, index=values.index)
    scaled = (numeric - lo) * 100.0 / (hi - lo)
    if direction == "cost":
        scaled = 100.0 - scaled
    return scaled.astype(float)


def hard_exclusion_reasons(
    candidates: gpd.GeoDataFrame,
    constraints: gpd.GeoDataFrame,
    *,
    required_fields: dict[str, object] | None = None,
    constraint_types: list[str] | None = None,
    constraint_buffer_m: float = 0.0,
) -> dict[str, list[str]]:
    """Apply configured attribute and spatial exclusions in a projected CRS."""
    if constraint_buffer_m < 0:
        raise ValueError("constraint_buffer_m must be non-negative")
    metric_candidates = candidates.to_crs(CRS_METRIC)
    metric_constraints = constraints.to_crs(CRS_METRIC)
    selected = metric_constraints
    if constraint_types:
        selected = selected.loc[selected["constraint_type"].isin(constraint_types)]
    exclusion_union = selected.geometry.buffer(constraint_buffer_m).union_all() if len(selected) else None
    reasons: dict[str, list[str]] = {}
    for _, row in metric_candidates.iterrows():
        site_id = str(row["candidate_id"])
        why = []
        for field, required_value in (required_fields or {}).items():
            if field not in row or row[field] != required_value:
                why.append(f"{field} must equal {required_value!r}")
        if exclusion_union is not None and row.geometry.intersects(exclusion_union):
            why.append(f"within {constraint_buffer_m:g} m of configured environmental constraint")
        reasons[site_id] = why
    return reasons


def evaluate_suitability(
    candidates: gpd.GeoDataFrame,
    constraints: gpd.GeoDataFrame,
    facility_type: FacilityType,
    *,
    weights: dict[str, float] | None = None,
    pairwise_matrix: list[list[float]] | None = None,
    required_fields: dict[str, object] | None = None,
    constraint_types: list[str] | None = None,
    constraint_buffer_m: float = 0.0,
) -> tuple[pd.DataFrame, AHPResult | None]:
    if "candidate_type" not in candidates:
        raise ValueError("Candidate layer is missing candidate_type")
    candidates = candidates.loc[candidates["candidate_type"] == facility_type].copy()
    if candidates.empty:
        raise ValueError(f"No candidates available for facility type {facility_type}")
    criteria = list(CRITERIA[facility_type])
    names = [item.name for item in criteria]
    if pairwise_matrix is not None and weights is not None:
        raise ValueError("Provide either AHP pairwise_matrix or explicit weights, not both")
    ahp = ahp_weights(names, pairwise_matrix) if pairwise_matrix is not None else None
    if weights is None:
        weights = ahp.weights if ahp else {name: 1.0 / len(names) for name in names}
    if set(weights) != set(names) or any(not np.isfinite(v) or v < 0 for v in weights.values()):
        raise ValueError(f"Weights must be non-negative and include exactly {names}")
    total_weight = sum(weights.values())
    if total_weight <= 0:
        raise ValueError("At least one criterion weight must be positive")
    normalized_weights = {name: value / total_weight for name, value in weights.items()}
    for criterion in criteria:
        if criterion.field not in candidates:
            raise ValueError(f"Candidate layer is missing criterion field {criterion.field}")
    exclusions = hard_exclusion_reasons(
        candidates, constraints, required_fields=required_fields,
        constraint_types=constraint_types, constraint_buffer_m=constraint_buffer_m)
    result = candidates[["candidate_id", "candidate_type", "geometry"]].copy()
    result["facility_type"] = facility_type
    result["eligible"] = result["candidate_id"].astype(str).map(lambda key: not exclusions[key])
    result["exclusion_reasons"] = result["candidate_id"].astype(str).map(exclusions)
    for criterion in criteria:
        result[f"raw_{criterion.name}"] = candidates[criterion.field].astype(float)
        result[f"normalized_{criterion.name}"] = normalize_criterion(
            candidates[criterion.field], criterion.direction)
        result[f"contribution_{criterion.name}"] = result[f"normalized_{criterion.name}"] * normalized_weights[criterion.name]
    contribution_fields = [f"contribution_{name}" for name in names]
    result["score"] = result[contribution_fields].sum(axis=1).clip(0, 100)
    eligible_order = result.loc[result.eligible].sort_values(
        ["score", "candidate_id"], ascending=[False, True], kind="mergesort").index
    result["rank"] = pd.Series(pd.NA, index=result.index, dtype="Int64")
    result.loc[eligible_order, "rank"] = range(1, len(eligible_order) + 1)
    result = result.sort_values(["eligible", "score", "candidate_id"],
                                ascending=[False, False, True], kind="mergesort").reset_index(drop=True)
    return result, ahp


def to_geojson(results: pd.DataFrame) -> dict:
    """Serialize ranked records with WGS84 GeoJSON-compatible point geometries."""
    frame = gpd.GeoDataFrame(results, geometry="geometry", crs=getattr(results, "crs", None) or "EPSG:4326")
    frame = frame.set_crs("EPSG:4326", allow_override=True) if frame.crs is None else frame.to_crs("EPSG:4326")
    return json.loads(frame.to_json(drop_id=True, na="null"))

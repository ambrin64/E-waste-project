"""Local vector loading and explicit data-quality validation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import geopandas as gpd
from pyproj import CRS


@dataclass
class LayerValidation:
    name: str
    path: str
    crs: str | None
    feature_count: int
    missing_fields: list[str] = field(default_factory=list)
    missing_values: dict[str, list[str]] = field(default_factory=dict)
    invalid_geometries: list[str] = field(default_factory=list)
    duplicate_ids: list[str] = field(default_factory=list)
    uncovered_candidate_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any((self.missing_fields, self.missing_values, self.invalid_geometries, self.duplicate_ids,
                        self.uncovered_candidate_ids, self.errors))


@dataclass
class DatasetBundle:
    wards: gpd.GeoDataFrame
    roads: gpd.GeoDataFrame
    constraints: gpd.GeoDataFrame
    candidates: gpd.GeoDataFrame
    validations: list[LayerValidation]
    manifest: dict[str, Any]


REQUIRED_FIELDS = {
    "wards": {"ward_id", "label", "data_status", "synthetic"},
    "roads": {"road_id", "road_class", "data_status", "synthetic"},
    "constraints": {"constraint_id", "constraint_type", "data_status", "synthetic"},
    "candidates": {
        "candidate_id", "candidate_type", "demand_access", "road_access",
        "land_cost", "environmental_risk", "industrial_compatibility",
        "data_status", "synthetic",
    },
}
ID_FIELDS = {"wards": "ward_id", "roads": "road_id", "constraints": "constraint_id",
             "candidates": "candidate_id"}


def load_vector(path: str | Path) -> gpd.GeoDataFrame:
    """Load a local vector file; missing CRS and unreadable geometry are errors."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Spatial dataset does not exist: {source}")
    frame = gpd.read_file(source)
    if frame.crs is None:
        raise ValueError(f"Spatial dataset has no CRS: {source}")
    return frame


def validate_layer(name: str, path: str | Path, frame: gpd.GeoDataFrame) -> LayerValidation:
    result = LayerValidation(name=name, path=str(path), crs=str(frame.crs) if frame.crs else None,
                             feature_count=len(frame))
    result.missing_fields = sorted(REQUIRED_FIELDS[name] - set(frame.columns))
    for required in REQUIRED_FIELDS[name] & set(frame.columns):
        missing = frame[required].isna()
        if missing.any():
            id_field = ID_FIELDS[name]
            result.missing_values[required] = frame.loc[missing, id_field].astype(str).tolist() if id_field in frame else frame.index[missing].astype(str).tolist()
    if "geometry" not in frame:
        result.errors.append("geometry column is missing")
    else:
        bad = frame.geometry.isna() | frame.geometry.is_empty | ~frame.geometry.is_valid
        result.invalid_geometries = [str(v) for v in frame.loc[bad, ID_FIELDS[name]].tolist()] if ID_FIELDS[name] in frame else [str(i) for i in frame.index[bad]]
    key = ID_FIELDS[name]
    if key in frame:
        result.duplicate_ids = sorted(frame.loc[frame[key].duplicated(keep=False), key].astype(str).unique().tolist())
    if name == "candidates" and "synthetic" in frame and not frame["synthetic"].fillna(False).all():
        result.errors.append("synthetic demo layer contains a feature not marked synthetic")
    return result


def load_dataset(paths: dict[str, str | Path], manifest_path: str | Path) -> DatasetBundle:
    """Read and validate all required local layers and candidate ward coverage."""
    expected = set(REQUIRED_FIELDS)
    if set(paths) != expected:
        raise ValueError(f"Layer paths must contain exactly {sorted(expected)}")
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    _validate_manifest(manifest)
    frames: dict[str, gpd.GeoDataFrame] = {}
    validations: list[LayerValidation] = []
    for name in ("wards", "roads", "constraints", "candidates"):
        frame = load_vector(paths[name])
        frames[name] = frame
        validations.append(validate_layer(name, paths[name], frame))
    if any(not item.valid for item in validations):
        raise DatasetValidationError(validations)

    target_crs = frames["wards"].crs
    for name, frame in frames.items():
        if not frame.crs.equals(target_crs):
            frames[name] = frame.to_crs(target_crs)
    wards = frames["wards"]
    candidates = frames["candidates"]
    coverage = wards.geometry.union_all()
    uncovered = ~candidates.geometry.covered_by(coverage)
    if uncovered.any():
        issue = next(v for v in validations if v.name == "candidates")
        issue.uncovered_candidate_ids = candidates.loc[uncovered, "candidate_id"].astype(str).tolist()
    if any(not item.valid for item in validations):
        raise DatasetValidationError(validations)
    return DatasetBundle(wards, frames["roads"], frames["constraints"], candidates,
                         validations, manifest)


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        raise TypeError("Dataset manifest must be a JSON object")
    required = {"dataset_id", "name", "status", "synthetic", "source", "source_year",
                "licence", "coordinate_reference_system"}
    missing = sorted(required - set(manifest))
    if missing:
        raise ValueError(f"Dataset manifest is missing required metadata: {missing}")
    if manifest["status"] not in {"official", "estimated", "synthetic_demo"}:
        raise ValueError("Dataset manifest status must be official, estimated, or synthetic_demo")
    if not isinstance(manifest["synthetic"], bool):
        raise TypeError("Dataset manifest synthetic flag must be boolean")
    if (manifest["status"] == "synthetic_demo") != manifest["synthetic"]:
        raise ValueError("Dataset manifest status conflicts with synthetic flag")
    for field_name in ("dataset_id", "name", "source", "licence"):
        if not isinstance(manifest[field_name], str) or not manifest[field_name].strip():
            raise ValueError(f"Dataset manifest {field_name} must be a non-empty string")
    year = manifest["source_year"]
    if year is not None and (isinstance(year, bool) or not isinstance(year, int) or year < 0):
        raise ValueError("Dataset manifest source_year must be a non-negative integer or null")
    try:
        CRS.from_user_input(manifest["coordinate_reference_system"])
    except Exception as exc:
        raise ValueError("Dataset manifest coordinate_reference_system is invalid") from exc


class DatasetValidationError(ValueError):
    def __init__(self, validations: list[LayerValidation]):
        self.validations = validations
        problems = [f"{v.name}: " + "; ".join(
            ([f"missing fields {v.missing_fields}"] if v.missing_fields else []) +
            ([f"missing values {v.missing_values}"] if v.missing_values else []) +
            ([f"invalid geometries {v.invalid_geometries}"] if v.invalid_geometries else []) +
            ([f"duplicate IDs {v.duplicate_ids}"] if v.duplicate_ids else []) +
            ([f"uncovered candidates {v.uncovered_candidate_ids}"] if v.uncovered_candidate_ids else []) + v.errors)
                    for v in validations if not v.valid]
        super().__init__("; ".join(problems))

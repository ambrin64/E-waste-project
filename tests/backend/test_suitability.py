import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point, Polygon

from app.decision.suitability import ahp_weights, evaluate_suitability, normalize_criterion
from app.gis.pipeline import DatasetValidationError, load_dataset, validate_layer


def test_normalization_benefit_cost_and_constant_values():
    values = pd.Series([10, 20, 30])
    assert normalize_criterion(values, "benefit").tolist() == [0, 50, 100]
    assert normalize_criterion(values, "cost").tolist() == [100, 50, 0]
    assert normalize_criterion(pd.Series([7, 7, 7]), "cost").tolist() == [100, 100, 100]


def test_ahp_calculates_weights_and_consistency():
    result = ahp_weights(["a", "b", "c"], [[1, 2, 4], [.5, 1, 2], [.25, .5, 1]])
    assert result.weights["a"] == pytest.approx(4 / 7)
    assert result.weights["b"] == pytest.approx(2 / 7)
    assert result.weights["c"] == pytest.approx(1 / 7)
    assert result.consistency_ratio == pytest.approx(0)
    assert result.consistency_acceptable


def test_ahp_rejects_nonreciprocal_matrix():
    with pytest.raises(ValueError, match="reciprocal"):
        ahp_weights(["a", "b"], [[1, 3], [1, 1]])


def test_ahp_reports_unacceptable_inconsistency():
    result = ahp_weights(["a", "b", "c"], [[1, 9, 1 / 9], [1 / 9, 1, 9], [9, 1 / 9, 1]])
    assert result.consistency_ratio > 0.1
    assert not result.consistency_acceptable


def _analysis_inputs():
    candidates = gpd.GeoDataFrame([
        {"candidate_id": "A", "candidate_type": "collection_centre", "demand_access": 100,
         "road_access": 80, "land_cost": 10, "environmental_risk": 5,
         "industrial_compatibility": 50, "hard_allowed": True, "geometry": Point(77.50, 12.95)},
        {"candidate_id": "B", "candidate_type": "collection_centre", "demand_access": 50,
         "road_access": 60, "land_cost": 30, "environmental_risk": 10,
         "industrial_compatibility": 50, "hard_allowed": True, "geometry": Point(77.52, 12.95)},
        {"candidate_id": "C", "candidate_type": "collection_centre", "demand_access": 80,
         "road_access": 90, "land_cost": 15, "environmental_risk": 8,
         "industrial_compatibility": 50, "hard_allowed": False, "geometry": Point(77.54, 12.95)},
        {"candidate_id": "D", "candidate_type": "dismantling_facility", "demand_access": 40,
         "road_access": 70, "land_cost": 20, "environmental_risk": 15,
         "industrial_compatibility": 90, "hard_allowed": True, "geometry": Point(77.56, 12.95)},
    ], crs="EPSG:4326")
    constraints = gpd.GeoDataFrame([
        {"constraint_type": "wetland", "geometry": Polygon([(77.519, 12.949), (77.521, 12.949), (77.521, 12.951), (77.519, 12.951)])}
    ], crs="EPSG:4326")
    return candidates, constraints


def test_hard_attribute_and_spatial_exclusions_are_explained():
    candidates, constraints = _analysis_inputs()
    results, _ = evaluate_suitability(candidates, constraints, "collection_centre",
                                      required_fields={"hard_allowed": True},
                                      constraint_types=["wetland"])
    by_id = results.set_index("candidate_id")
    assert not by_id.loc["B", "eligible"]
    assert "environmental constraint" in by_id.loc["B", "exclusion_reasons"][0]
    assert not by_id.loc["C", "eligible"]
    assert "hard_allowed" in by_id.loc["C", "exclusion_reasons"][0]


def test_rankings_are_deterministic_and_collection_dismantling_models_differ():
    candidates, constraints = _analysis_inputs()
    first, _ = evaluate_suitability(candidates, constraints, "collection_centre",
                                    required_fields={"hard_allowed": True}, constraint_types=["wetland"])
    second, _ = evaluate_suitability(candidates, constraints, "collection_centre",
                                     required_fields={"hard_allowed": True}, constraint_types=["wetland"])
    assert first[["candidate_id", "score", "rank"]].equals(second[["candidate_id", "score", "rank"]])
    dismantling, _ = evaluate_suitability(candidates, constraints, "dismantling_facility",
                                          required_fields={"hard_allowed": True}, constraint_types=["wetland"])
    assert "raw_demand_access" in first and "raw_demand_access" not in dismantling
    assert "raw_industrial_compatibility" not in first and "raw_industrial_compatibility" in dismantling


def test_invalid_geometry_is_reported():
    frame = gpd.GeoDataFrame([{"ward_id": "bad", "label": "bad", "data_status": "synthetic_demo",
                               "synthetic": True, "geometry": Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])}],
                             crs="EPSG:4326")
    report = validate_layer("wards", "invalid.geojson", frame)
    assert not report.valid
    assert report.invalid_geometries == ["bad"]


def test_missing_fields_and_duplicate_ids_are_reported():
    frame = gpd.GeoDataFrame([{"ward_id": "same", "geometry": Point(0, 0)},
                              {"ward_id": "same", "geometry": Point(1, 1)}], crs="EPSG:4326")
    report = validate_layer("wards", "bad.geojson", frame)
    assert "label" in report.missing_fields
    assert report.duplicate_ids == ["same"]


def test_local_pipeline_reports_candidates_outside_ward_coverage(tmp_path):
    layers = {
        "wards": gpd.GeoDataFrame([{"ward_id": "W1", "label": "Synthetic ward", "data_status": "synthetic_demo",
                                    "synthetic": True, "geometry": Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])}], crs="EPSG:4326"),
        "roads": gpd.GeoDataFrame([{"road_id": "R1", "road_class": "synthetic", "data_status": "synthetic_demo",
                                    "synthetic": True, "geometry": LineString([(0, 0), (1, 1)])}], crs="EPSG:4326"),
        "constraints": gpd.GeoDataFrame([{"constraint_id": "E1", "constraint_type": "demo", "data_status": "synthetic_demo",
                                          "synthetic": True, "geometry": Polygon([(0, 0), (.1, 0), (.1, .1), (0, .1)])}], crs="EPSG:4326"),
        "candidates": gpd.GeoDataFrame([{"candidate_id": "OUT", "candidate_type": "collection_centre", "demand_access": 1,
            "road_access": 1, "land_cost": 1, "environmental_risk": 1, "industrial_compatibility": 1,
            "data_status": "synthetic_demo", "synthetic": True, "geometry": Point(2, 2)}], crs="EPSG:4326"),
    }
    paths = {}
    for name, frame in layers.items():
        paths[name] = tmp_path / f"{name}.geojson"
        frame.to_file(paths[name], driver="GeoJSON")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"dataset_id": "fixture", "name": "Fixture",
        "status": "synthetic_demo", "synthetic": True, "source": "generated test data",
        "source_year": None, "licence": "CC0-1.0", "coordinate_reference_system": "EPSG:4326"}),
        encoding="utf-8")
    with pytest.raises(DatasetValidationError, match="uncovered candidates"):
        load_dataset(paths, manifest)

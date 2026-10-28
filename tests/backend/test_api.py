import pytest
from fastapi.testclient import TestClient
from shapely.geometry import shape

from app.core.dataset import clear_dataset_cache
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_data():
    clear_dataset_cache()
    yield
    clear_dataset_cache()


def test_health_and_demo_dataset_routes():
    assert client.get("/api/v1/health").json() == {"status": "ok", "api_version": "v1"}
    response = client.get("/api/v1/datasets")
    assert response.status_code == 200
    assert response.json()["items"][0]["synthetic"] is True
    assert client.get("/api/v1/datasets/wards/features").json()["type"] == "FeatureCollection"


def test_sourced_city_catalog_and_ward_geojson():
    response = client.get("/api/v1/cities")
    assert response.status_code == 200
    cities = {item["city_id"]: item for item in response.json()["items"]}
    assert set(cities) == {"bengaluru", "mumbai"}
    assert cities["bengaluru"]["boundary"]["feature_count"] == 369
    assert cities["mumbai"]["boundary"]["feature_count"] == 24

    mumbai = client.get("/api/v1/cities/mumbai/wards")
    assert mumbai.status_code == 200
    body = mumbai.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 24
    first = body["features"][0]["properties"]
    assert first["synthetic"] is False
    assert first["population_year"] == 2023
    assert first["population_is_e_waste_demand"] is False
    assert sum(feature["properties"]["population_estimate"] for feature in body["features"]) == 13_014_389
    for city_id, expected_count in (("bengaluru", 369), ("mumbai", 24)):
        wards = client.get(f"/api/v1/cities/{city_id}/wards")
        assert wards.status_code == 200
        assert len(wards.json()["features"]) == expected_count
        ids = [feature["properties"]["ward_id"] for feature in wards.json()["features"]]
        assert len(set(ids)) == expected_count
        assert all(shape(feature["geometry"]).is_valid for feature in wards.json()["features"])
        all_bounds = [shape(feature["geometry"]).bounds for feature in wards.json()["features"]]
        min_lon = min(bounds[0] for bounds in all_bounds)
        min_lat = min(bounds[1] for bounds in all_bounds)
        max_lon = max(bounds[2] for bounds in all_bounds)
        max_lat = max(bounds[3] for bounds in all_bounds)
        if city_id == "mumbai":
            assert 72.6 < min_lon < max_lon < 73.2
            assert 18.7 < min_lat < max_lat < 19.4
        else:
            assert 77.2 < min_lon < max_lon < 78.0
            assert 12.6 < min_lat < max_lat < 13.4


def test_city_ward_endpoint_rejects_unknown_city():
    response = client.get("/api/v1/cities/not-a-city/wards")
    assert response.status_code == 404


def test_suitability_response_is_ranked_geojson_with_explanations():
    response = client.post("/api/v1/suitability/evaluate", json={
        "facility_type": "collection_centre", "constraint_types": ["synthetic_sensitive_use"],
        "required_fields": {"hard_allowed": True}, "constraint_buffer_m": 0,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data_status"] == "synthetic_demo"
    features = body["geojson"]["features"]
    assert len(features) == 6
    assert all("score" in item["properties"] and "exclusion_reasons" in item["properties"] for item in features)
    assert sorted(f["properties"]["rank"] for f in features if f["properties"]["eligible"]) == list(range(1, 6))
    excluded = next(f for f in features if f["properties"]["candidate_id"] == "SYN-C02")
    assert excluded["properties"]["eligible"] is False
    assert "hard_allowed" in excluded["properties"]["exclusion_reasons"][0]


def test_suitability_endpoint_accepts_ahp_comparisons_and_reports_consistency():
    response = client.post("/api/v1/suitability/evaluate", json={
        "facility_type": "collection_centre",
        "pairwise_matrix": [[1, 2, 4, 4], [.5, 1, 2, 2], [.25, .5, 1, 1], [.25, .5, 1, 1]],
        "required_fields": {"hard_allowed": True},
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ahp"]["consistency_acceptable"] is True
    assert body["ahp"]["consistency_ratio"] == pytest.approx(0)
    assert sum(body["weights"].values()) == pytest.approx(1)

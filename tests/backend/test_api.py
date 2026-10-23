import pytest
from fastapi.testclient import TestClient

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

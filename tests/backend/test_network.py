import json

import geopandas as gpd
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point

from app.core.dataset import clear_dataset_cache, get_dataset
from app.main import app
from app.optimization.network import solve_network
from app.routing.roads import RoadRouter

client = TestClient(app)


def request_payload(**overrides):
    params = {
        "scenario_type": "optimized", "label": "test optimized", "facility_type": "collection_centre",
        "demand_by_ward": {f"SYN-W{i}": tonnes for i, tonnes in enumerate([8, 12, 10, 15, 9])},
        "fixed_costs": {f"SYN-C0{i}": 180000 + (i - 1) * 25000 for i in range(1, 7)},
        "capacities": {f"SYN-C0{i}": 20 + (i - 1) * 5 for i in range(1, 7)},
        "budget": 400000, "max_facilities": 2, "transport_cost_per_tonne_km": 1.4,
        "unserved_penalty_per_tonne": 1000000,
        "constraint_types": ["synthetic_waterbody", "synthetic_sensitive_use"],
    }
    params.update(overrides)
    return params


@pytest.fixture(autouse=True)
def reset_data():
    clear_dataset_cache()
    yield
    clear_dataset_cache()


def test_budget_capacity_and_demand_accounting():
    result = solve_network(get_dataset(), request_payload())
    opened = result["selected_facilities"]
    assert sum(item["fixed_cost"] for item in opened) <= 400000
    assert len(opened) <= 2
    allocated_per_site = {}
    for allocation in result["allocations"]:
        allocated_per_site[allocation["candidate_id"]] = allocated_per_site.get(allocation["candidate_id"], 0) + allocation["tonnes"]
        assert allocation["route"]["routing_method"] == "road_graph_plus_explicit_access_connectors"
        assert allocation["route"]["road_network_distance_m"] >= 0
    for item in opened:
        assert allocated_per_site.get(item["candidate_id"], 0) <= item["capacity_tonnes"]
    assert result["allocated_tonnes"] + result["unserved_tonnes"] == pytest.approx(result["total_demand_tonnes"])
    assert result["status"] == "partial"


def test_infeasible_budget_and_capacity_are_explained():
    budget_result = solve_network(get_dataset(), request_payload(budget=0))
    assert budget_result["unserved_tonnes"] == pytest.approx(54)
    assert budget_result["feasibility_explanation"]
    capacity_result = solve_network(get_dataset(), request_payload(capacities={f"SYN-C0{i}": 2 for i in range(1, 7)}))
    assert capacity_result["unserved_tonnes"] > 0
    assert capacity_result["feasibility_explanation"]


def test_deterministic_solution_and_rankings():
    first = solve_network(get_dataset(), request_payload())
    second = solve_network(get_dataset(), request_payload())
    assert first["selected_facilities"] == second["selected_facilities"]
    assert first["allocations"] == second["allocations"]
    assert first["candidate_scores"] == second["candidate_scores"]


def test_run_retrieve_and_compare_scenarios(tmp_path, monkeypatch):
    db_file = tmp_path / "scenarios.sqlite3"
    monkeypatch.setenv("EWASTE_SCENARIO_DB", str(db_file))
    baseline = request_payload(scenario_type="baseline", label="baseline", baseline_facility_ids=["SYN-C01"],
                               budget=400000, max_facilities=1)
    optimized = request_payload(label="optimized")
    first = client.post("/api/v1/scenarios/run", json=baseline)
    second = client.post("/api/v1/scenarios/run", json=optimized)
    assert first.status_code == second.status_code == 200, first.text + second.text
    a, b = first.json(), second.json()
    assert client.get(f"/api/v1/scenarios/{a['run_id']}").json()["results"] == a["results"]
    comparison = client.post("/api/v1/scenarios/compare", json={"run_ids": [a["run_id"], b["run_id"]]}).json()
    comparison_again = client.post("/api/v1/scenarios/compare", json={"run_ids": [a["run_id"], b["run_id"]]}).json()
    assert len(comparison["runs"]) == 2
    assert comparison_again == comparison
    assert client.get("/api/v1/scenarios", params={"group_id": a["group_id"]}).json()["items"]
    assert json.loads(json.dumps(b["results"]["geojson"]))["type"] == "FeatureCollection"


def test_baseline_over_budget_sites_return_detail_and_affordable_selection_succeeds():
    demo = client.get("/api/v1/scenarios/demo-inputs").json()
    suitability = client.post("/api/v1/suitability/evaluate", json={
        "facility_type": "collection_centre", "constraint_buffer_m": 0,
        "constraint_types": ["synthetic_waterbody", "synthetic_sensitive_use"],
        "required_fields": {"hard_allowed": True},
    }).json()
    request = {
        "scenario_type": "baseline", "label": "Baseline", "facility_type": "collection_centre",
        "input_data_status": demo["data_status"], "demand_by_ward": demo["demand_by_ward"],
        "fixed_costs": demo["fixed_costs"], "capacities": demo["capacities"],
        "budget": 400000, "max_facilities": 2, "transport_cost_per_tonne_km": 1.4,
        "criteria_weights": suitability["weights"],
        "constraint_types": ["synthetic_waterbody", "synthetic_sensitive_use"],
        "constraint_buffer_m": 0, "required_fields": {"hard_allowed": True},
    }

    # The highest-ranked second site (SYN-C06) makes this baseline cost 485,000.
    invalid = client.post("/api/v1/scenarios/run", json=request | {
        "baseline_facility_ids": ["SYN-C01", "SYN-C06"],
    })
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "No feasible facility subset; check budget and facility-count constraints"

    # Budget-aware ranking keeps the affordable top site and proceeds normally.
    valid = client.post("/api/v1/scenarios/run", json=request | {
        "baseline_facility_ids": ["SYN-C01"],
    })
    assert valid.status_code == 200, valid.text
    assert valid.json()["results"]["selected_facilities"][0]["candidate_id"] == "SYN-C01"


def test_invalid_inputs_are_rejected_by_api():
    payload = request_payload(demand_by_ward={"SYN-W0": 1})
    assert client.post("/api/v1/scenarios/run", json=payload).status_code == 422


def test_disconnected_road_graph_does_not_fall_back_to_straight_line():
    roads = gpd.GeoDataFrame({"geometry": [
        LineString([(77.50, 12.95), (77.51, 12.95)]),
        LineString([(77.55, 12.95), (77.56, 12.95)]),
    ]}, crs="EPSG:4326")
    router = RoadRouter(roads)
    assert router.distance(Point(77.505, 12.95), Point(77.555, 12.95)) is None

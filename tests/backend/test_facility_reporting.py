import csv
import hashlib
import io
import json

import pytest
from app.facility.design import build_layout
from app.gis.demo_data import build_demo_layers
from app.main import app
from app.reporting.pdf import facility_layout_pdf
from fastapi.testclient import TestClient

client = TestClient(app)


def assert_valid_pdf(data: bytes):
    assert data.startswith(b"%PDF-1.4")
    startxref = int(data.rsplit(b"startxref\n", 1)[1].splitlines()[0])
    assert data[startxref:startxref + 4] == b"xref"
    xref_lines = data[startxref:].splitlines()
    count = int(xref_lines[1].split()[1])
    for object_number, entry in enumerate(xref_lines[3:3 + count - 1], start=1):
        offset = int(entry[:10])
        assert data[offset:].startswith(f"{object_number} 0 obj".encode())


def test_seeded_synthetic_demo_layers_are_reproducible(tmp_path):
    first = build_demo_layers(tmp_path / "first")
    second = build_demo_layers(tmp_path / "second")
    for name in first:
        digest1 = hashlib.sha256(first[name].read_bytes()).hexdigest()
        digest2 = hashlib.sha256(second[name].read_bytes()).hexdigest()
        assert digest1 == digest2
    manifest = json.loads((tmp_path / "first" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["generation_seed"] == 20260617
    assert manifest["status"] == "synthetic_demo" and manifest["synthetic"] is True


def test_facility_defaults_plan_and_layout_pdf_are_dimension_aware():
    defaults = client.get("/api/v1/facility-design/defaults")
    assert defaults.status_code == 200
    inputs = defaults.json()["defaults"]
    assert inputs["plot_width_m"] == 40
    assert inputs["plot_depth_m"] == 40
    assert "not an approval" in defaults.json()["warning"]
    plan = client.post("/api/v1/facility-design/plan", json=inputs)
    assert plan.status_code == 200, plan.text
    result = plan.json()
    assert result["annual_throughput_tonnes"] == pytest.approx(1500)
    assert result["storage_capacity_tonnes"] == pytest.approx(35)
    expected_areas = {"receiving": 4, "inspection": 2.5, "dismantling": 15,
                      "segregated_storage": 87.5, "dispatch": 3.5, "circulation": 28.125}
    assert {zone["zone_id"]: zone["area_m2"] for zone in result["zones"]} == pytest.approx(expected_areas)
    assert result["process_area_m2"] == pytest.approx(112.5)
    assert result["required_area_m2"] == pytest.approx(140.625)
    assert result["remaining_area_m2"] == pytest.approx(1459.375)
    for zone in result["zones"]:
        assert zone["x_m"] >= 0 and zone["y_m"] >= 0
        assert zone["x_m"] + zone["width_m"] <= result["envelope"]["width_m"] + 1e-8
        assert zone["y_m"] + zone["depth_m"] <= result["envelope"]["depth_m"] + 1e-8
        assert zone["width_m"] == pytest.approx(zone["depth_m"])
        assert zone["width_m"] * zone["depth_m"] == pytest.approx(zone["area_m2"])
    exported = client.post("/api/v1/facility-design/layout.pdf", json=inputs)
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/pdf"
    assert_valid_pdf(exported.content)


def test_layout_rejects_process_areas_larger_than_plot_envelope():
    defaults = client.get("/api/v1/facility-design/defaults").json()["defaults"]
    defaults.update({"plot_width_m": 10, "plot_depth_m": 10})
    response = client.post("/api/v1/facility-design/plan", json=defaults)
    assert response.status_code == 422
    assert "exceeding the configured" in response.json()["detail"]


def test_facility_grid_preserves_areas_is_contained_and_has_no_zone_overlap():
    defaults = client.get("/api/v1/facility-design/defaults").json()["defaults"]
    layout = build_layout(defaults)
    env = layout["envelope"]
    zones = layout["zones"]
    assert len(zones) == 6
    assert {zone["y_m"] for zone in zones} == {0.0}
    assert sum(zone["width_m"] for zone in zones) == pytest.approx(23.9846, abs=0.01)
    for zone in zones:
        assert zone["x_m"] >= 0 and zone["y_m"] >= 0
        assert zone["x_m"] + zone["width_m"] <= env["width_m"] + 1e-8
        assert zone["y_m"] + zone["depth_m"] <= env["depth_m"] + 1e-8
        assert zone["width_m"] * zone["depth_m"] == pytest.approx(zone["area_m2"])
    for i, a in enumerate(zones):
        for b in zones[i + 1:]:
            overlap_x = min(a["x_m"] + a["width_m"], b["x_m"] + b["width_m"]) - max(a["x_m"], b["x_m"])
            overlap_y = min(a["y_m"] + a["depth_m"], b["y_m"] + b["depth_m"]) - max(a["y_m"], b["y_m"])
            assert overlap_x <= 1e-8 or overlap_y <= 1e-8
    assert sum(z["area_m2"] for z in zones) == pytest.approx(layout["required_area_m2"])
    assert layout["required_area_m2"] == pytest.approx(layout["process_area_m2"] + layout["circulation_area_m2"])
    assert layout["envelope_area_m2"] == pytest.approx(layout["required_area_m2"] + layout["remaining_area_m2"])


def test_facility_layout_is_deterministic_and_recalculates_assumptions():
    defaults = client.get("/api/v1/facility-design/defaults").json()["defaults"]
    first = build_layout(defaults)
    assert build_layout(defaults) == first
    changed = build_layout(defaults | {"daily_throughput_tonnes_per_day": 6,
                                       "storage_duration_days": 9, "plot_width_m": 90})
    assert changed["storage_capacity_tonnes"] != first["storage_capacity_tonnes"]
    assert changed["envelope"]["width_m"] == 90
    assert changed["required_area_m2"] > first["required_area_m2"]


def test_grid_fit_failure_is_explained_without_shrinking_zones():
    defaults = client.get("/api/v1/facility-design/defaults").json()["defaults"]
    # Total zone area fits this envelope, but exact-width grid rows do not fit its depth.
    defaults.update({"plot_width_m": 10, "plot_depth_m": 20})
    with pytest.raises(ValueError, match="No non-overlapping one-row or two-row area-preserving layout fits"):
        build_layout(defaults)


def test_facility_pdf_contains_corrected_zone_dimensions_and_scale_grid():
    defaults = client.get("/api/v1/facility-design/defaults").json()["defaults"]
    layout = build_layout(defaults)
    pdf = facility_layout_pdf(layout)
    assert_valid_pdf(pdf)
    # Filled vector rectangles are emitted from each returned x/y/width/depth.
    pdf_scale = min(480 / layout["envelope"]["width_m"], 550 / layout["envelope"]["depth_m"])
    expected_width = f"{layout['zones'][0]['width_m'] * pdf_scale}"
    expected_height = f"{layout['zones'][0]['depth_m'] * pdf_scale}"
    assert f"{expected_width} {expected_height} re B".encode() in pdf
    assert b"Process 112.5 m2; circulation 28.1 m2" in pdf
    assert b"ENLARGED ZONE DETAIL - SAME METRE GEOMETRY" in pdf
    assert b"Detail extent 23.98 m x 9.35 m" in pdf


def test_saved_scenario_pdf_and_csv_include_comparison_validation_and_limitations(tmp_path, monkeypatch):
    monkeypatch.setenv("EWASTE_SCENARIO_DB", str(tmp_path / "reports.sqlite3"))
    demo = client.get("/api/v1/scenarios/demo-inputs").json()
    group = "report-test-group"
    common = {"group_id": group, "facility_type": "collection_centre", "input_data_status": "synthetic_demo",
        "demand_by_ward": demo["demand_by_ward"], "fixed_costs": demo["fixed_costs"],
        "capacities": demo["capacities"], "budget": 400000, "max_facilities": 2,
        "transport_cost_per_tonne_km": 1.4}
    opt_response = client.post("/api/v1/scenarios/run", json={**common,
        "scenario_type": "optimized", "label": "Optimized"})
    assert opt_response.status_code == 200, opt_response.text
    assert client.post("/api/v1/scenarios/run", json={**common, "scenario_type": "baseline",
        "label": "Baseline", "max_facilities": 1, "baseline_facility_ids": ["SYN-C01"]}).status_code == 200
    assert client.post("/api/v1/scenarios/run", json={**common, "scenario_type": "future_demand",
        "label": "Future", "future_growth_percent": 20}).status_code == 200
    run_id = opt_response.json()["run_id"]
    pdf = client.get(f"/api/v1/reports/{run_id}.pdf")
    assert pdf.status_code == 200
    assert_valid_pdf(pdf.content)
    assert b"VALIDATION" in pdf.content and b"LIMITATIONS" in pdf.content
    csv_response = client.get(f"/api/v1/reports/{run_id}.csv")
    assert csv_response.status_code == 200
    rows = list(csv.reader(io.StringIO(csv_response.content.decode("utf-8-sig"))))
    sections = {row[0] for row in rows[1:]}
    assert {"provenance", "assumption", "candidate_ranking", "selected_facility", "allocation",
            "scenario_comparison", "validation", "limitation"} <= sections
    assert sum(row[0] == "scenario_comparison" for row in rows) == 3

"""Versioned API endpoints."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from app.api.facility_schemas import FacilityDesignRequest
from app.api.scenario_schemas import (
    ScenarioComparisonRequest,
    ScenarioRunRequest,
    ScenarioRunResponse,
)
from app.api.schemas import AHPResponse, SuitabilityRequest, SuitabilityResponse
from app.core.dataset import get_dataset
from app.db.scenarios import get_run, list_runs, save_run
from app.decision.suitability import CRITERIA, evaluate_suitability, to_geojson
from app.facility.design import DEFAULTS, build_layout
from app.gis.pipeline import DatasetValidationError
from app.optimization.network import solve_network
from app.reporting.pdf import facility_layout_pdf
from app.reporting.reports import report_csv, report_pdf

router = APIRouter(prefix="/api/v1")
CITY_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "cities"


@router.get("/health", tags=["health"])
def health():
    return {"status": "ok", "api_version": "v1"}


@router.get("/cities", tags=["datasets"], summary="List cities with sourced ward boundaries",
            description="City records include ward-boundary provenance and population attributes where available. This does not imply that candidate, road, constraint, or e-waste-demand layers are available for every city.")
def cities():
    items = []
    for manifest_path in sorted(CITY_DATA_DIR.glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        items.append({key: manifest.get(key) for key in (
            "city_id", "name", "boundary", "population", "analysis_availability")})
    return {"items": items}


@router.get("/cities/{city_id}/wards", tags=["datasets"], summary="Get sourced city wards as GeoJSON",
            description="Returns locally stored, source-attributed municipal ward polygons in EPSG:4326. Population attributes retain their own year and source.")
def city_wards(city_id: str):
    if not city_id.replace("-", "").isalnum():
        raise HTTPException(status_code=404, detail="Unknown city")
    path = CITY_DATA_DIR / city_id / "layers" / "wards.geojson"
    manifest_path = CITY_DATA_DIR / city_id / "manifest.json"
    if not path.is_file() or not manifest_path.is_file():
        raise HTTPException(status_code=404, detail="City ward dataset not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="City ward dataset could not be read") from exc
    if data.get("type") != "FeatureCollection":
        raise HTTPException(status_code=500, detail="City ward data is not a GeoJSON FeatureCollection")
    return data


@router.get("/datasets", tags=["datasets"], summary="List loaded datasets",
            description="Returns provenance metadata for the local vector layers. Synthetic demo metadata remains explicitly labelled.")
def datasets():
    bundle = get_dataset()
    return {"items": [{"dataset_id": bundle.manifest.get("dataset_id"),
                        "name": bundle.manifest.get("name"),
                        "status": bundle.manifest.get("status"),
                        "synthetic": bundle.manifest.get("synthetic"),
                        "source": bundle.manifest.get("source"),
                        "source_year": bundle.manifest.get("source_year"),
                        "licence": bundle.manifest.get("licence"),
                        "generation_seed": bundle.manifest.get("generation_seed"),
                        "generation_method": bundle.manifest.get("generation_method"),
                        "crs": "EPSG:4326"}]}


@router.get("/datasets/{layer}/features", tags=["datasets"], summary="Get a dataset layer as GeoJSON",
            description="Layers are loaded from local vector files, validated, and returned in WGS 84 for browser mapping.")
def dataset_features(layer: str):
    bundle = get_dataset()
    if layer not in {"wards", "roads", "constraints", "candidates"}:
        raise HTTPException(status_code=404, detail="Unknown dataset layer")
    frame = getattr(bundle, layer).to_crs("EPSG:4326")
    return json.loads(frame.to_json(drop_id=True, na="null"))


@router.post("/suitability/evaluate", response_model=SuitabilityResponse,
             responses={422: {"model": dict}}, tags=["suitability"],
             summary="Evaluate and rank candidate sites",
             description="Applies facility-specific criteria, min-max 0 to 100 normalization, optional AHP weights, and configured attribute/spatial hard exclusions. Metric buffers use EPSG:32643. Excluded candidates are returned with reasons and no eligible rank.")
def suitability(request: SuitabilityRequest):
    try:
        bundle = get_dataset()
        result, ahp = evaluate_suitability(
            bundle.candidates, bundle.constraints, request.facility_type,
            weights=request.weights, pairwise_matrix=request.pairwise_matrix,
            required_fields=request.required_fields,
            constraint_types=request.constraint_types or None,
            constraint_buffer_m=request.constraint_buffer_m)
    except (ValueError, DatasetValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    criteria = CRITERIA[request.facility_type]
    resolved = ahp.weights if ahp else request.weights or {item.name: 1 / len(criteria) for item in criteria}
    total = sum(resolved.values())
    normalized_weights = {key: value / total for key, value in resolved.items()}
    return SuitabilityResponse(
        facility_type=request.facility_type, model_version="suitability-v1",
        data_status=str(bundle.manifest.get("status", "unknown")),
        criteria_directions={item.name: item.direction for item in criteria},
        weights=normalized_weights, ahp=AHPResponse(**vars(ahp)) if ahp else None,
        assumptions=list(bundle.manifest.get("assumptions", [])) + [
            "Criterion values use min-max normalization over the loaded candidate set.",
            "Constant-valued criteria normalize to 100 for all candidates.",
            f"Environmental exclusion buffer is user-configured as {request.constraint_buffer_m:g} metres."],
        validation=[v.__dict__ | {"valid": v.valid} for v in bundle.validations],
        geojson=to_geojson(result))


@router.post("/scenarios/run", response_model=ScenarioRunResponse, tags=["scenarios"],
             summary="Run and persist a network scenario",
             description="Optimizes facility subsets under fixed-cost budget and facility-count limits, and allocates ward demand through road-graph shortest paths. Access connectors are explicit estimates; disconnected routes are never replaced with straight-line distances.")
def run_scenario(request: ScenarioRunRequest):
    try:
        bundle = get_dataset()
        params = request.model_dump(exclude_none=True)
        results = solve_network(bundle, params)
        group_id = request.group_id or str(uuid.uuid4())
        weights = results.get("criteria_weights", request.criteria_weights or {})
        stored = save_run(group_id, request.scenario_type, request.label,
            str(bundle.manifest.get("dataset_id", "unknown")), params, weights, results)
        return {"run_id": stored["run_id"], "group_id": stored["group_id"],
            "created_at": stored["created_at"], "dataset_version": stored["dataset_version"],
            "parameters": stored["parameters"], "criteria_weights": stored["criteria_weights"],
            "results": stored["results"]}
    except (ValueError, DatasetValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/scenarios", tags=["scenarios"], summary="List saved scenario runs")
def scenarios(group_id: str | None = None):
    return {"items": list_runs(group_id)}


@router.post("/scenarios/compare", tags=["scenarios"], summary="Compare saved scenario KPIs")
def compare_scenarios(request: ScenarioComparisonRequest):
    runs = [get_run(run_id) for run_id in request.run_ids]
    missing = [run_id for run_id, item in zip(request.run_ids, runs) if item is None]
    if missing:
        raise HTTPException(status_code=404, detail=f"Scenario runs not found: {missing}")
    metrics = ("total_demand_tonnes", "allocated_tonnes", "unserved_tonnes", "service_coverage_percent",
               "total_estimated_operating_cost", "transport_distance_km", "transport_tonne_km",
               "capacity_utilization_percent")
    baseline = runs[0]["results"]
    return {"runs": [{"run_id": item["run_id"], "label": item["label"],
        "scenario_type": item["scenario_type"], "results": item["results"]} for item in runs],
        "delta_from_first": {metric: {item["run_id"]: item["results"].get(metric, 0) - baseline.get(metric, 0)
            for item in runs[1:]} for metric in metrics}}


@router.get("/scenarios/demo-inputs", tags=["scenarios"], summary="Get labelled synthetic scenario inputs")
def scenario_demo_inputs():
    bundle = get_dataset()
    if bundle.manifest.get("status") != "synthetic_demo":
        raise HTTPException(status_code=409,
            detail="Synthetic defaults are only served for the labelled demo dataset. Supply verified ward demand, fixed costs and capacities in scenario requests.")
    collection = bundle.candidates.loc[bundle.candidates.candidate_type == "collection_centre", "candidate_id"].astype(str).tolist()
    dismantling = bundle.candidates.loc[bundle.candidates.candidate_type == "dismantling_facility", "candidate_id"].astype(str).tolist()
    ward_ids = bundle.wards.ward_id.astype(str).tolist()
    return {"data_status": "synthetic_demo", "synthetic": True,
        "assumption": "Illustrative annual ward demand, facility costs and capacities; replace with verified data for planning.",
        "demand_by_ward": {ward: [8, 12, 10, 15, 9][idx] for idx, ward in enumerate(ward_ids)},
        "fixed_costs": {cid: (180000 + idx * 25000) for idx, cid in enumerate(collection)},
        "capacities": {cid: (20 + idx * 5) for idx, cid in enumerate(collection)},
        "dismantling_fixed_costs": {cid: (800000 + idx * 100000) for idx, cid in enumerate(dismantling)},
        "dismantling_capacities": {cid: (120 + idx * 40) for idx, cid in enumerate(dismantling)}}


@router.get("/scenarios/{run_id}", response_model=ScenarioRunResponse, tags=["scenarios"],
            summary="Retrieve a saved scenario")
def scenario(run_id: str):
    found = get_run(run_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Scenario run not found")
    return {"run_id": found["run_id"], "group_id": found["group_id"],
        "created_at": found["created_at"], "dataset_version": found["dataset_version"],
        "parameters": found["parameters"], "criteria_weights": found["criteria_weights"],
        "results": found["results"]}


@router.get("/facility-design/defaults", tags=["facility design"], summary="Get conceptual facility sizing assumptions")
def facility_design_defaults():
    return {"defaults": DEFAULTS, "zone_labels": {
        "receiving": "Receiving", "inspection": "Inspection", "dismantling": "Dismantling",
        "segregated_storage": "Segregated storage", "dispatch": "Dispatch", "circulation": "Circulation"},
        "status": "estimated_assumptions", "warning": "Conceptual planning only. The editable 40 x 40 m default plot is a rounded 1,600 m2 example for the 5 tonnes/day case, informed by a published clearance submission citing a 300 m2 per tonnes/day dismantling-area reference (1,500 m2 at 5 tonnes/day). This is a planning reference, not an approval, universal minimum, or engineering standard; check the actual process and site."}


@router.post("/facility-design/plan", tags=["facility design"], summary="Calculate and layout conceptual facility zones",
             description="Calculates throughput, storage and area requirements from editable assumptions, then lays out zones in local metres. Rejects any design whose required area exceeds its configured rectangular envelope.")
def facility_design_plan(request: FacilityDesignRequest):
    try:
        return build_layout(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/facility-design/layout.pdf", tags=["facility design"], summary="Export the conceptual facility layout as PDF")
def facility_design_layout_pdf(request: FacilityDesignRequest):
    try:
        content = facility_layout_pdf(build_layout(request.model_dump()))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": "attachment; filename=conceptual-facility-layout.pdf"})


def _saved_report(run_id: str):
    run = get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Scenario run not found")
    group = list_runs(run["group_id"])
    return run, group


@router.get("/reports/{run_id}.pdf", tags=["reports"], summary="Download a scenario PDF report")
def scenario_report_pdf(run_id: str):
    run, group = _saved_report(run_id)
    content = report_pdf(run, group)
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=scenario-{run_id}.pdf"})


@router.get("/reports/{run_id}.csv", tags=["reports"], summary="Download a scenario CSV report")
def scenario_report_csv(run_id: str):
    run, group = _saved_report(run_id)
    content = report_csv(run, group)
    return Response(content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=scenario-{run_id}.csv"})

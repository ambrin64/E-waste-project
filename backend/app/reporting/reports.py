"""CSV/PDF report content assembled only from persisted scenario snapshots."""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from app.reporting.pdf import text_report_pdf

LIMITATIONS = [
    "Conceptual decision support only; not engineering design, legal advice, regulatory approval, or compliance certification.",
    "No measured environmental benefits or emissions reductions are calculated.",
    "Synthetic or unverified values remain estimates and must be replaced with validated inputs.",
    "Road graph is undirected and does not model turn restrictions, travel time, congestion, or vehicle constraints.",
    "Access connectors are straight-line metric estimates, disclosed separately from road-network distance.",
    "Exact facility subset enumeration is intended for at most 20 candidate sites; allocations use 1 kg increments.",
]


def validate_saved_run(run: dict[str, Any]) -> list[dict[str, Any]]:
    p, r = run["parameters"], run["results"]
    selected = r["selected_facilities"]
    allocated_by_site: dict[str, float] = {}
    for item in r["allocations"]:
        allocated_by_site[item["candidate_id"]] = allocated_by_site.get(item["candidate_id"], 0.0) + item["tonnes"]
    fixed_total = sum(site["fixed_cost"] for site in selected)
    checks = [
        ("Demand reconciliation", abs(r["allocated_tonnes"] + r["unserved_tonnes"] - r["total_demand_tonnes"]) < 0.001,
         f"{r['allocated_tonnes']:.3f} allocated + {r['unserved_tonnes']:.3f} unserved vs {r['total_demand_tonnes']:.3f} total tonnes"),
        ("Fixed-cost budget", p.get("budget") is None or fixed_total <= p["budget"] + 1e-6,
         f"{fixed_total:.2f} fixed cost vs {p.get('budget', 'unbounded')} budget INR"),
        ("Facility count", len(selected) <= p["max_facilities"],
         f"{len(selected)} selected vs maximum {p['max_facilities']}"),
        ("Site capacity", all(allocated_by_site.get(site["candidate_id"], 0) <= site["capacity_tonnes"] + 0.001 for site in selected),
         "Allocated tonnes per selected site do not exceed configured capacities."),
        ("Road routing provenance", all(item["route"].get("routing_method") == "road_graph_plus_explicit_access_connectors" for item in r["allocations"]),
         "Allocated route records identify graph routes and access connectors."),
    ]
    return [{"check": name, "passed": passed, "detail": detail} for name, passed, detail in checks]


def _report_pages(run: dict[str, Any], comparison_runs: list[dict[str, Any]]) -> list[list[str]]:
    result, params = run["results"], run["parameters"]
    provenance = result.get("dataset_provenance", {})
    lines = [
        "BENGALURU E-WASTE FACILITY PLANNER - SCENARIO REPORT",
        "CONCEPTUAL DECISION SUPPORT - NOT FOR ENGINEERING OR REGULATORY APPROVAL",
        "",
        f"Run: {run['label']} | ID {run['run_id']}",
        f"Scenario type: {run['scenario_type']} | Created: {run['created_at']}",
        f"Dataset version: {run['dataset_version']} | Dataset status: {result.get('dataset_status', 'unknown')}",
        f"Input status: {result.get('scenario_input_data_status', 'unknown')}",
        f"Source: {provenance.get('source', 'Not captured')} | Year: {provenance.get('source_year', 'Not specified')}",
        f"Licence: {provenance.get('licence', 'Not specified')} | CRS: {provenance.get('coordinate_reference_system', 'Not specified')}",
        f"Fixture seed: {provenance.get('generation_seed', 'Not specified')} | Generation: {provenance.get('generation_method', 'Not specified')}",
        "",
        "INPUT ASSUMPTIONS",
    ]
    for key, value in sorted(params.items()):
        lines.append(f"{key}: {json.dumps(value, sort_keys=True, ensure_ascii=True)}")
    lines.append(f"criteria_weights: {json.dumps(run.get('criteria_weights', {}), sort_keys=True)}")
    lines.extend(["", "RESULTS", f"Status: {result['status']}",
        f"Demand: {result['total_demand_tonnes']:.3f} tonnes | Allocated: {result['allocated_tonnes']:.3f} | Unserved: {result['unserved_tonnes']:.3f}",
        f"Service coverage by demand volume: {result['service_coverage_percent']:.2f}%",
        f"Estimated total scenario cost: INR {result['total_estimated_operating_cost']:.2f} (fixed + transport)",
        f"Transport cost: INR {result['transport_cost']:.2f} | Average route: {result['transport_distance_km']:.3f} km",
        f"Transport work: {result['transport_tonne_km']:.3f} tonne-km | Capacity utilization: {result['capacity_utilization_percent']:.2f}%",
        "", "CANDIDATE RANKINGS"])
    for row in result["candidate_scores"]:
        lines.append(f"Rank {row['rank'] if row['rank'] is not None else '—'} | {row['candidate_id']} | eligible={row['eligible']} | score={row['suitability_score']:.2f} | reasons={'; '.join(row['exclusion_reasons']) or 'none'}")
    lines.extend(["", "SELECTED FACILITIES"])
    for site in result["selected_facilities"]:
        lines.append(f"{site['candidate_id']} | fixed INR {site['fixed_cost']:.2f} | capacity {site['capacity_tonnes']:.3f} t/year | suitability {site['suitability_score']:.2f}")
    lines.extend(["", "DEMAND ALLOCATIONS"])
    for item in result["allocations"]:
        route = item["route"]
        lines.append(f"{item['ward_id']} -> {item['candidate_id']}: {item['tonnes']:.3f} t; road {route['road_network_distance_m'] / 1000:.3f} km; access connectors {route['origin_access_connector_m'] / 1000:.3f}+{route['destination_access_connector_m'] / 1000:.3f} km")
    lines.extend(["", "SCENARIO COMPARISON", "Label | Type | Coverage | Unserved t | Total cost INR | Average route km"])
    for other in comparison_runs:
        r = other["results"]
    lines.append(f"{other['label']} | {other['scenario_type']} | coverage={r['service_coverage_percent']:.2f}% | unserved={r['unserved_tonnes']:.3f} t | cost={r['total_estimated_operating_cost']:.2f} INR | transport={r['transport_cost']:.2f} INR | avg route={r['transport_distance_km']:.3f} km | utilization={r['capacity_utilization_percent']:.2f}%")
    lines.extend(["", "VALIDATION"])
    for check in validate_saved_run(run):
        lines.append(f"{'PASS' if check['passed'] else 'FAIL'} | {check['check']} | {check['detail']}")
    lines.extend(["", "LIMITATIONS AND CAUTIONS", *LIMITATIONS,
        "No engineering approval, legal compliance certification, or measured environmental benefit is claimed.",
        "", "MODEL ASSUMPTIONS"])
    lines.extend(result.get("assumptions", []))
    return [lines[offset:offset + 46] for offset in range(0, len(lines), 46)]


def report_pdf(run: dict[str, Any], comparison_runs: list[dict[str, Any]]) -> bytes:
    return text_report_pdf(_report_pages(run, comparison_runs))


def report_csv(run: dict[str, Any], comparison_runs: list[dict[str, Any]]) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    result, params = run["results"], run["parameters"]
    writer.writerow(["section", "key", "value", "status_or_detail"])
    writer.writerow(["metadata", "run_id", run["run_id"], ""])
    writer.writerow(["metadata", "label", run["label"], ""])
    writer.writerow(["metadata", "scenario_type", run["scenario_type"], ""])
    writer.writerow(["metadata", "dataset_version", run["dataset_version"], result.get("dataset_status", "unknown")])
    writer.writerow(["provenance", "source", result.get("dataset_provenance", {}).get("source", "Not captured"), ""])
    writer.writerow(["provenance", "source_year", result.get("dataset_provenance", {}).get("source_year", "Not specified"), ""])
    writer.writerow(["provenance", "licence", result.get("dataset_provenance", {}).get("licence", "Not specified"), ""])
    writer.writerow(["provenance", "generation_seed", result.get("dataset_provenance", {}).get("generation_seed", "Not specified"), result.get("dataset_provenance", {}).get("generation_method", "")])
    writer.writerow(["provenance", "input_data_status", result.get("scenario_input_data_status", "unknown"), ""])
    for key, value in sorted(params.items()):
        writer.writerow(["assumption", key, json.dumps(value, sort_keys=True), ""])
    writer.writerow(["criteria_weights", "weights", json.dumps(run.get("criteria_weights", {}), sort_keys=True), ""])
    for key in ("total_demand_tonnes", "allocated_tonnes", "unserved_tonnes", "service_coverage_percent",
                "fixed_cost", "transport_cost", "total_estimated_operating_cost", "transport_distance_km",
                "transport_tonne_km", "capacity_utilization_percent"):
        writer.writerow(["kpi", key, result[key], ""])
    for item in result["candidate_scores"]:
        writer.writerow(["candidate_ranking", item["candidate_id"], item["suitability_score"],
                         f"rank={item['rank']};eligible={item['eligible']};reasons={' | '.join(item['exclusion_reasons'])}"])
    for site in result["selected_facilities"]:
        writer.writerow(["selected_facility", site["candidate_id"], site["capacity_tonnes"],
                         f"fixed_cost_INR={site['fixed_cost']};suitability={site['suitability_score']}"])
    for item in result["allocations"]:
        writer.writerow(["allocation", f"{item['ward_id']}->{item['candidate_id']}", item["tonnes"],
                         json.dumps(item["route"], sort_keys=True)])
    for other in comparison_runs:
        r = other["results"]
        writer.writerow(["scenario_comparison", other["label"], other["scenario_type"],
                         f"coverage={r['service_coverage_percent']};unserved_t={r['unserved_tonnes']};cost_INR={r['total_estimated_operating_cost']};transport_cost_INR={r['transport_cost']};average_route_km={r['transport_distance_km']};tonne_km={r['transport_tonne_km']};capacity_utilization_percent={r['capacity_utilization_percent']}"])
    for check in validate_saved_run(run):
        writer.writerow(["validation", check["check"], check["passed"], check["detail"]])
    for limitation in LIMITATIONS:
        writer.writerow(["limitation", limitation, "", ""])
    for assumption in result.get("assumptions", []):
        writer.writerow(["model_assumption", assumption, "", ""])
    return out.getvalue().encode("utf-8-sig")

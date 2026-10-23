"""Exact small-instance capacitated facility location using subset enumeration
and NetworkX min-cost flow. Facility subsets are enumerated; each fixed subset's
continuous allocation is solved as a min-cost flow with demand quantized to kg.
This is intended for planning instances up to 20 candidates, not city-scale MILP.
"""
from __future__ import annotations

import math
from itertools import combinations

import networkx as nx
import pandas as pd

from app.decision.suitability import CRITERIA, evaluate_suitability, to_geojson
from app.routing.roads import RoadRouter


def solve_network(bundle, request: dict) -> dict:
    facility_type = request["facility_type"]
    demand = {key: float(value) for key, value in request["demand_by_ward"].items()}
    candidates = bundle.candidates.loc[bundle.candidates.candidate_type == facility_type].copy()
    if len(candidates) > 20:
        raise ValueError("Exact site subset solver supports at most 20 candidates")
    weights = request.get("criteria_weights")
    scored, ahp = evaluate_suitability(candidates, bundle.constraints, facility_type,
        weights=weights, required_fields=request.get("required_fields", {"hard_allowed": True}),
        constraint_types=request.get("constraint_types", []),
        constraint_buffer_m=request.get("constraint_buffer_m", 0))
    eligible_ids = set(scored.loc[scored.eligible, "candidate_id"].astype(str))
    candidates = candidates.loc[candidates.candidate_id.astype(str).isin(eligible_ids)]
    fixed_costs = request["fixed_costs"]
    capacities = request["capacities"]
    if set(fixed_costs) != set(bundle.candidates.loc[bundle.candidates.candidate_type == facility_type, "candidate_id"].astype(str)):
        raise ValueError("fixed_costs must provide a value for every candidate of the selected type")
    if set(capacities) != set(fixed_costs):
        raise ValueError("capacities must provide a value for every candidate of the selected type")
    ward_ids = set(bundle.wards.ward_id.astype(str))
    if set(demand) != ward_ids:
        raise ValueError(f"demand_by_ward must include exactly these ward IDs: {sorted(ward_ids)}")
    if any(v < 0 or not math.isfinite(v) for v in [*demand.values(), *fixed_costs.values(), *capacities.values()]):
        raise ValueError("Demand, costs, and capacities must be finite and non-negative")

    router = RoadRouter(bundle.roads)
    ward_points = bundle.wards.set_index(bundle.wards.ward_id.astype(str)).geometry
    candidate_points = candidates.set_index(candidates.candidate_id.astype(str)).geometry
    routes = {}
    for ward_id, origin in ward_points.items():
        origin = origin.representative_point() if origin.geom_type != "Point" else origin
        for candidate_id, destination in candidate_points.items():
            routes[(ward_id, candidate_id)] = router.distance(origin, destination)

    # The future-demand multiplier is an explicit scenario assumption.
    multiplier = 1 + float(request.get("future_growth_percent", 0)) / 100
    demand = {key: round(value * multiplier * 1000) / 1000 for key, value in demand.items()}
    demand_kg = {key: round(value * 1000) for key, value in demand.items()}
    total_demand = sum(demand.values())
    available = sorted(candidates.candidate_id.astype(str))
    forced = request.get("baseline_facility_ids") if request["scenario_type"] == "baseline" else None
    if forced is not None:
        unknown = set(forced) - set(fixed_costs)
        if unknown:
            raise ValueError(f"Unknown baseline facility IDs: {sorted(unknown)}")
        ineligible = set(forced) - set(available)
        if ineligible:
            raise ValueError(f"Baseline facilities are ineligible under current hard exclusions: {sorted(ineligible)}")
        available = [candidate for candidate in available if candidate in set(forced)]
    budget = request.get("budget")
    max_count = int(request["max_facilities"])
    transport_rate = float(request["transport_cost_per_tonne_km"])
    penalty = float(request.get("unserved_penalty_per_tonne", 1_000_000))
    values = [transport_rate, penalty, float(request.get("future_growth_percent", 0))]
    if budget is not None:
        values.append(float(budget))
    if (not all(math.isfinite(value) for value in values) or max_count < 0
            or transport_rate < 0 or penalty < 0 or (budget is not None and budget < 0)):
        raise ValueError("Budget, count and cost parameters must be non-negative")
    if len(available) > 20:
        raise ValueError("Exact site subset solver supports at most 20 eligible candidates")
    best = None
    rejected_budget_sets = 0
    for count in range(min(max_count, len(available)) + 1):
        for opened_tuple in combinations(available, count):
            if forced is not None and set(opened_tuple) != set(forced):
                continue
            opened = set(opened_tuple)
            fixed = sum(float(fixed_costs[key]) for key in opened)
            if budget is not None and fixed > budget + 1e-8:
                rejected_budget_sets += 1
                continue
            graph = nx.DiGraph()
            source, sink = "__source__", "__sink__"
            graph.add_node(source, demand=-sum(demand_kg.values()))
            graph.add_node(sink, demand=sum(demand_kg.values()))
            for ward_id in demand:
                wn = f"ward:{ward_id}"
                kg = demand_kg[ward_id]
                graph.add_node(wn, demand=0)
                graph.add_edge(source, wn, capacity=kg, weight=0)
                unserved = f"unserved:{ward_id}"
                graph.add_node(unserved, demand=0)
                graph.add_edge(wn, unserved, capacity=kg,
                               weight=round(penalty / 1000 * 1_000_000))
                graph.add_edge(unserved, sink, capacity=kg, weight=0)
                for candidate_id in opened:
                    route = routes.get((ward_id, candidate_id))
                    if route is None:
                        continue
                    cost_per_kg = transport_rate * route["estimated_total_distance_m"] / 1000 / 1000
                    graph.add_edge(wn, f"site:{candidate_id}", capacity=kg,
                                   weight=max(0, round(cost_per_kg * 1_000_000)))
            for candidate_id in opened:
                site = f"site:{candidate_id}"
                graph.add_node(site, demand=0)
                graph.add_edge(site, sink,
                    capacity=math.floor(float(capacities[candidate_id]) * 1000 + 1e-9), weight=0)
            try:
                flow_cost, flows = nx.network_simplex(graph)
            except (nx.NetworkXUnfeasible, nx.NetworkXError):
                continue
            # Cost weights are micro-INR/kg; convert to estimated INR and add fixed costs.
            variable_cost = flow_cost / 1_000_000
            objective = variable_cost + fixed
            if best is None or (objective, tuple(opened_tuple)) < (best["objective"], tuple(best["opened"])):
                allocation = {}
                for ward_id in demand:
                    ward_node = f"ward:{ward_id}"
                    allocation[ward_id] = {candidate_id: amount / 1000
                        for candidate_id, amount in ((site.removeprefix("site:"), qty)
                        for site, qty in flows[ward_node].items()
                        if site.startswith("site:") and qty > 0)}
                unserved_by_ward = {ward_id: flows[f"ward:{ward_id}"].get(f"unserved:{ward_id}", 0) / 1000
                                    for ward_id in demand}
                best = {"opened": sorted(opened), "allocation": allocation,
                    "unserved_by_ward": unserved_by_ward, "objective": objective,
                    "fixed_cost": fixed, "transport_cost": variable_cost}
    if best is None:
        raise ValueError("No feasible facility subset; check budget and facility-count constraints")

    allocated = sum(sum(row.values()) for row in best["allocation"].values())
    unserved = sum(best["unserved_by_ward"].values())
    served_wards = {ward for ward, amount in best["unserved_by_ward"].items() if amount < demand[ward]}
    total_capacity = sum(float(capacities[c]) for c in best["opened"])
    reasons = []
    if unserved > 0:
        if total_capacity + 1e-9 < total_demand:
            reasons.append("Opened facility capacity is below total demand.")
        if not best["opened"]:
            reasons.append("No facility could be opened under the budget/facility-count constraints.")
        unreachable = [w for w in demand if not any(routes.get((w, c)) for c in best["opened"])]
        if unreachable:
            reasons.append("No road-network route is available from wards: " + ", ".join(unreachable) + ".")
        if not reasons:
            reasons.append("Available capacity or eligible road-reachable sites cannot serve all demand.")
    scores = scored.set_index("candidate_id")
    resolved_weights = ahp.weights if ahp else weights or {
        item.name: 1 / len(CRITERIA[facility_type]) for item in CRITERIA[facility_type]}
    weight_total = sum(resolved_weights.values())
    resolved_weights = {key: value / weight_total for key, value in resolved_weights.items()}
    result = {
        "status": "feasible" if unserved <= 1e-6 else "partial",
        "dataset_status": str(bundle.manifest.get("status", "unknown")),
        "dataset_provenance": {key: bundle.manifest.get(key) for key in (
            "dataset_id", "name", "source", "source_year", "licence",
            "coordinate_reference_system", "status", "synthetic", "assumptions",
            "generation_seed", "generation_method")},
        "scenario_input_data_status": request.get("input_data_status", "estimated"),
        "scenario_type": request["scenario_type"], "facility_type": facility_type,
        "selected_facilities": [{"candidate_id": cid, "fixed_cost": float(fixed_costs[cid]),
            "capacity_tonnes": float(capacities[cid]), "suitability_score": float(scores.loc[cid, "score"])}
            for cid in best["opened"]],
        "allocations": [{"ward_id": w, "candidate_id": c, "tonnes": tonnes,
            "route": routes[(w, c)]} for w, row in best["allocation"].items()
            for c, tonnes in row.items() if tonnes > 0],
        "unserved_by_ward": best["unserved_by_ward"], "total_demand_tonnes": total_demand,
        "allocated_tonnes": allocated, "unserved_tonnes": unserved,
        "service_coverage_percent": 100 * allocated / max(total_demand, 1e-12),
        "wards_with_any_service": len(served_wards),
        "total_estimated_operating_cost": best["fixed_cost"] + best["transport_cost"],
        "fixed_cost": best["fixed_cost"],
        "transport_cost": best["transport_cost"],
        "optimization_objective_cost": best["objective"],
        "transport_tonne_km": sum(a["tonnes"] * a["route"]["estimated_total_distance_m"] / 1000
                                      for a in [{"tonnes": tonnes, "route": routes[(w, c)]}
                                      for w, row in best["allocation"].items() for c, tonnes in row.items()]),
        "transport_distance_km": (sum(a["tonnes"] * a["route"]["estimated_total_distance_m"] / 1000
                                      for a in [{"tonnes": tonnes, "route": routes[(w, c)]}
                                      for w, row in best["allocation"].items() for c, tonnes in row.items()])
                                  / max(allocated, 1e-12)),
        "capacity_utilization_percent": 100 * allocated / max(total_capacity, 1e-12),
        "criteria_weights": resolved_weights,
        "feasibility_explanation": reasons,
        "routing_method": "road_graph_plus_explicit_access_connectors",
        "assumptions": ["Demand and capacities are annual tonnes.",
            "Point access connector lengths are shown separately from road-network distance.",
            "Access connectors snap to the nearest road vertex and are estimated in straight-line metric distance.",
            "Transport cost is estimated from tonne-kilometres and the user-supplied rate.",
            "Demand is allocated in 1 kg increments for exact integer min-cost flow.",
            "Subset enumeration is exact for at most 20 candidate facilities.",
            f"Scenario input values are labelled {request.get('input_data_status', 'estimated')}.",
            f"Loaded spatial dataset is labelled {bundle.manifest.get('status', 'unknown')}."],
        "candidate_scores": [{"candidate_id": str(row.candidate_id), "eligible": bool(row.eligible),
            "suitability_score": float(row.score), "rank": None if pd.isna(row.rank) else int(row.rank),
            "exclusion_reasons": row.exclusion_reasons} for row in scored.itertuples()],
    }
    geojson = to_geojson(scored)
    selected = set(best["opened"])
    allocations_by_site = {candidate: sum(row.get(candidate, 0) for row in best["allocation"].values())
                           for candidate in selected}
    for feature in geojson["features"]:
        cid = feature["properties"]["candidate_id"]
        feature["properties"].update({"selected": cid in selected,
            "allocated_tonnes": allocations_by_site.get(cid, 0.0)})
    result["geojson"] = geojson
    return result

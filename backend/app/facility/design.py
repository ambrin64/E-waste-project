"""Dimension-aware conceptual facility sizing and 2D zoning.

The layout is a planning sketch, not an engineering drawing. Zone sizing factors
are editable assumptions and all coordinates are local metres from plot origin.
"""
from __future__ import annotations

import math
from itertools import combinations
from typing import Any

DEFAULTS = {
    "daily_throughput_tonnes_per_day": 5.0,
    "operating_days_per_year": 300,
    "storage_duration_days": 7.0,
    "plot_width_m": 80.0,
    "plot_depth_m": 60.0,
    "receiving_area_m2_per_tpd": 0.8,
    "inspection_area_m2_per_tpd": 0.5,
    "dismantling_area_m2_per_tpd": 3.0,
    "storage_area_m2_per_stored_tonne": 2.5,
    "dispatch_area_m2_per_tpd": 0.7,
    "circulation_fraction": 0.25,
}

ZONE_LABELS = {
    "receiving": "Receiving",
    "inspection": "Inspection",
    "dismantling": "Dismantling",
    "segregated_storage": "Segregated storage",
    "dispatch": "Dispatch",
    "circulation": "Circulation",
}


def build_layout(parameters: dict[str, Any]) -> dict[str, Any]:
    """Pack exact-area, area-derived square zones in two conceptual rows.

    A square footprint is used only as a plotting convention: its side is
    sqrt(required area), so no zone is enlarged, reduced, or assigned a
    fabricated standard dimension. The two-row packing is not an engineering
    recommendation.
    """
    p = DEFAULTS | parameters
    daily = float(p["daily_throughput_tonnes_per_day"])
    operating_days = int(p["operating_days_per_year"])
    storage_days = float(p["storage_duration_days"])
    width, depth = float(p["plot_width_m"]), float(p["plot_depth_m"])
    numeric = [daily, storage_days, width, depth, *(float(p[k]) for k in (
        "receiving_area_m2_per_tpd", "inspection_area_m2_per_tpd",
        "dismantling_area_m2_per_tpd", "storage_area_m2_per_stored_tonne",
        "dispatch_area_m2_per_tpd", "circulation_fraction"))]
    if any(not math.isfinite(value) for value in numeric) or any(value < 0 for value in numeric) or daily <= 0 or width <= 0 or depth <= 0:
        raise ValueError("Throughput and plot dimensions must be positive; durations and factors cannot be negative")
    if operating_days <= 0 or operating_days > 366:
        raise ValueError("Operating days per year must be between 1 and 366")
    annual = daily * operating_days
    stored_tonnes = daily * storage_days
    base_areas = {
        "receiving": daily * float(p["receiving_area_m2_per_tpd"]),
        "inspection": daily * float(p["inspection_area_m2_per_tpd"]),
        "dismantling": daily * float(p["dismantling_area_m2_per_tpd"]),
        "segregated_storage": stored_tonnes * float(p["storage_area_m2_per_stored_tonne"]),
        "dispatch": daily * float(p["dispatch_area_m2_per_tpd"]),
    }
    base_area = sum(base_areas.values())
    base_areas["circulation"] = base_area * float(p["circulation_fraction"])
    total_required = sum(base_areas.values())
    envelope_area = width * depth
    if total_required > envelope_area + 1e-8:
        raise ValueError(
            f"Required zones total {total_required:.2f} m2, exceeding the configured "
            f"{envelope_area:.2f} m2 facility envelope by {total_required - envelope_area:.2f} m2. "
            "Increase plot dimensions or revise the documented zone sizing assumptions."
        )

    items = list(base_areas.items())
    sides = [math.sqrt(area) for _, area in items]
    # Use one ordered process row when it fits. For narrower plots, evaluate
    # every 3/3 assignment and choose the most compact two-row square packing.
    if sum(sides) <= width + 1e-8 and max(sides) <= depth + 1e-8:
        row_indexes = [list(range(len(items)))]
        row_heights = [max(sides)]
    else:
        best = None
        diagnostic = None
        for first_indexes in combinations(range(len(items)), 3):
            first = set(first_indexes)
            second = set(range(len(items))) - first
            groups = [sorted(first), sorted(second)]
            row_widths = [sum(sides[i] for i in group) for group in groups]
            row_heights = [max((sides[i] for i in group), default=0.0) for group in groups]
            needed_depth = sum(row_heights)
            diagnostic_key = (max(row_widths), needed_depth, first_indexes)
            if diagnostic is None or diagnostic_key < diagnostic[0]:
                diagnostic = (diagnostic_key, groups, row_widths, row_heights)
            if max(row_widths) <= width + 1e-8 and needed_depth <= depth + 1e-8:
                key = (max(row_widths) * needed_depth, needed_depth, max(row_widths), first_indexes)
                if best is None or key < best[0]:
                    best = (key, groups, row_heights)
        if best is None:
            assert diagnostic is not None
            min_width, min_depth = diagnostic[0][:2]
            raise ValueError(
                "No non-overlapping one-row or two-row area-preserving layout fits "
                "the configured plot using the documented square-footprint packing "
                f"convention: the closest two-row packing needs at least {min_width:.2f} m "
                f"of width and {min_depth:.2f} m of depth, while the plot is "
                f"{width:.2f} m by {depth:.2f} m. Increase the plot dimensions or "
                "revise the documented sizing assumptions; zones are not shrunk."
            )
        _, row_indexes, row_heights = best
    zones = []
    y = 0.0
    for row, indexes in enumerate(row_indexes):
        x = 0.0
        for item_index in indexes:
            zone_id, area = items[item_index]
            side = sides[item_index]
            zones.append({"zone_id": zone_id, "label": ZONE_LABELS[zone_id],
                "x_m": x, "y_m": y, "width_m": side,
                "depth_m": side, "area_m2": area})
            x += side
        y += row_heights[row]
    # Return zones in the API's original semantic order, independent of row.
    zones.sort(key=lambda zone: next(i for i, (key, _) in enumerate(items) if key == zone["zone_id"]))

    return {
        "layout_type": "conceptual_not_engineering_drawing",
        "units": {"throughput": "tonnes/day", "annual_throughput": "tonnes/year",
                  "storage": "tonnes", "dimensions": "metres", "areas": "square metres"},
        "inputs": p,
        "annual_throughput_tonnes": annual,
        "storage_capacity_tonnes": stored_tonnes,
        "required_area_m2": total_required,
        "process_area_m2": base_area,
        "circulation_area_m2": base_areas["circulation"],
        "envelope_area_m2": envelope_area,
        "remaining_area_m2": max(0.0, envelope_area - total_required),
        "envelope": {"width_m": width, "depth_m": depth},
        "zones": zones,
        "assumptions": [
            "Annual throughput equals daily throughput multiplied by operating days per year.",
            "Storage capacity equals daily throughput multiplied by configured storage duration.",
            "Receiving, inspection, dismantling and dispatch areas use editable m2 per tonne/day factors.",
            "Segregated storage uses an editable m2 per stored tonne factor.",
            "Circulation area is a configured fraction of process-zone area and is counted once as a separate zone.",
            "Each zone is represented as a square with side sqrt(calculated area), preserving its area exactly. Zones are placed in source order in one row when it fits, otherwise in a deterministic compact two-row packing; square footprints and row placement are visualization conventions, not engineering standards.",
            "Unallocated area equals envelope area minus all five process zones and the separate circulation zone; no zone area is counted twice.",
            "Layout is conceptual only and excludes structural, fire, accessibility, utilities, setbacks and code checks.",
        ],
    }

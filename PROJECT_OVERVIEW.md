# Bengaluru E-Waste GIS Facility Planner

## What this project is

The Bengaluru E-Waste GIS Facility Planner is a local, explainable planning tool for exploring where e-waste collection centres and a dismantling facility might be located, and how a small network of facilities could serve ward-level demand.

It combines a map, site suitability analysis, network scenarios, conceptual facility sizing, and downloadable reports. It is intended to help people compare assumptions and understand why results change. It does not make a final siting decision for a planner.

## What is in the demonstration

The bundled Bengaluru data is **synthetic demonstration data**. It is reproducible, but it does not represent official ward boundaries, road data, facility locations, population, e-waste generation, environmental observations, or verified costs. The dataset manifest records its status and provenance. The map and reports should be read with those labels in mind.

The planner can:

- Display ward areas, roads, environmental constraints, and candidate locations on an interactive map.
- Compare collection-centre and dismantling-facility candidates using separate suitability models.
- Show weighted scores, criterion contributions, eligibility, and hard-exclusion reasons.
- Accept AHP pairwise comparisons and report whether their consistency is acceptable.
- Compare baseline, optimized, and future-demand network scenarios under budget, capacity, and facility-count constraints.
- Allocate ward demand to selected sites using available road-network routes and show transport and coverage estimates.
- Estimate annual throughput and storage, then draw a conceptual, area-based facility layout.
- Export saved scenario results as PDF or CSV and export the conceptual facility layout as PDF.

## Typical demonstration workflow

1. Start the local API and web app using the instructions in [TECHNICAL_GUIDE.md](TECHNICAL_GUIDE.md).
2. Review the map and suitability rankings. Inspect exclusion reasons and score breakdowns before comparing candidates.
3. Set a budget, facility limit, costs, or capacities in the network scenario section, then run the baseline, optimized, and future-demand scenarios.
4. Review the returned map, allocations, coverage, capacity use, transport estimates, and feasibility explanations.
5. Use the facility designer to change throughput, storage duration, or plot dimensions and recalculate. Export the conceptual layout if needed.
6. Open Reports to download PDF and CSV files for a completed scenario run.

## How to interpret the results

Suitability scores are relative to the loaded candidate dataset and selected criteria weights. A site can have a score and still be excluded by a hard rule; the exclusion takes precedence over the score. Scenario outputs depend on the entered demand, fixed costs, capacities, budget, transport-rate assumptions, road data, and criteria weights.

The facility designer calculates process-zone areas from editable sizing factors. Circulation is calculated as a configured fraction of process-zone area and shown as one separate conceptual zone. Its layout is an area-preserving diagram, not an architectural or engineering design. Unallocated plot area is plot area minus the modeled process and circulation areas.

All estimated and synthetic values should be identified as such. The application does not establish engineering approval, legal compliance, regulatory suitability, or measured environmental benefits. It does not include construction design, fire/accessibility reviews, real-world route validation, or field verification.

## Project structure

- `frontend/` — the React application and interactive map.
- `backend/app/` — the FastAPI service, GIS pipeline, decision models, network simulation, facility design, and reporting.
- `data/demo/` — the seeded synthetic dataset and manifest.
- `tests/` — backend API/calculation tests and frontend UI tests.
- `scripts/demo.ps1` — a local demonstration workflow.
- `README.md` — quick setup and API notes.
- `TECHNICAL_GUIDE.md` — a plain-language guide to the software and data flow.


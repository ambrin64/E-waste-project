# Bengaluru E-Waste GIS Facility Planner

## Purpose and first delivery

This project will provide an explainable planning workflow for synthetic or sourced Bengaluru spatial data. The first implementation milestone is intentionally small: load the labelled demo dataset, show it on a Leaflet map, compute collection-centre candidate scores in the API, and display a ranked list with score explanations. No official Bengaluru spatial data has been bundled.

## Proposed architecture

```text
React + TypeScript + Vite
  map / dataset / suitability / scenarios / facility design / reports
        | JSON over HTTP (OpenAPI)
FastAPI API: schemas, routes, persistence adapters
  GIS services | suitability and AHP | allocation/optimization | routing
  facility design | scenario comparison | report generation
        |                         |
SQLite (application records)   GeoPackage (spatial input/output)
```

The UI is a presentation client; domain calculations live in Python services. GeoPandas/Shapely operate on spatial data, and all metric distance/area work uses a projected CRS. WGS 84 (EPSG:4326) is only for web map interchange/display. The demo uses an explicitly synthetic local coordinate plane around Bengaluru, transformed to EPSG:4326 for display; it must not be interpreted as actual ward or facility data.

### Proposed source layout

- `frontend/src/{app,components,features,lib,types}`: React app, map, screens, API client and generated/hand-maintained API types.
- `backend/app/api`: versioned routers and Pydantic request/response schemas.
- `backend/app/core`: settings and shared errors.
- `backend/app/db`: SQLite connection, schema and repositories.
- `backend/app/gis`: import, validation, CRS handling and spatial operations.
- `backend/app/decision`: AHP, consistency checks, exclusions and explainable scoring.
- `backend/app/optimization`: capacity/budget selection and demand allocation.
- `backend/app/routing`: graph construction and route/cost estimates.
- `backend/app/facility`: capacity calculations and conceptual 2D layout.
- `backend/app/reporting`: CSV/PDF exports and provenance.
- `data/demo`: deterministic synthetic fixture and manifest; `data/processed`: generated GeoPackage (ignored).
- `tests`: backend unit/API tests and frontend component tests.

## Dependency baseline

Minimum supported dependency versions are recorded in `backend/pyproject.toml`; frontend direct versions are pinned in `frontend/package.json`. The Python package resolver selects a compatible build for the local runtime. Python 3.12+ and Node 22+ are the proposed runtimes. GeoPandas includes native GEOS/GDAL/PROJ dependencies; use wheels or conda-forge if the platform cannot resolve them reliably.

| Area | Compatibility floor |
| --- | --- |
| Python API / validation | FastAPI >=0.115.12, Pydantic >=2.11.4, Uvicorn >=0.34.2 |
| GIS / data | GeoPandas >=1.0.1, Shapely >=2.0.7, PyProj >=3.7.1, Pandas >=2.2.3 |
| Graph / optimization | NetworkX >=3.4.2, OR-Tools >=9.12.4544 |
| Persistence / reports | SQLAlchemy >=2.0.40, GeoAlchemy2 >=0.17.1, ReportLab >=4.4.1 |
| Backend quality | pytest >=8.3.5, httpx >=0.28.1, Ruff >=0.11.8 |
| Frontend | React 19.1.0, TypeScript 5.8.3, Vite 6.3.5, Tailwind 3.4.17 |
| Mapping / charts | Leaflet 1.9.4, React-Leaflet 5.0.0, Recharts 2.15.3 |
| Frontend quality | Vitest 3.1.2, Testing Library 16.3.0, Playwright 1.52.0 |

GIS/API/test dependencies are installed for this milestone; OR-Tools and reporting/persistence dependencies are optional extras for their later stages. The compatibility floors allow pip to select wheels for the local Python runtime. Generate a lockfile once the supported runtime matrix is chosen.

## API contracts (v1 proposal)

All endpoints are rooted at `/api/v1`; JSON geometry uses GeoJSON WGS 84 coordinates. Errors use FastAPI's standard validation envelope plus a stable `code` and human-readable `detail` for domain errors.

| Method / path | Request | Response |
| --- | --- | --- |
| `GET /health` | none | `{status: "ok", api_version: "v1"}` |
| `GET /datasets` | optional `kind`, `status` | `{items: DatasetMetadata[]}` |
| `GET /datasets/{id}/features` | `layer`, optional bbox | GeoJSON `FeatureCollection` |
| `POST /suitability/evaluate` | `SuitabilityRequest` | `SuitabilityResult` with ordered candidates, criterion contributions and exclusion reasons |
| `POST /scenarios` | `ScenarioCreate` | persisted `Scenario` |
| `GET /scenarios/{id}` | none | `Scenario` and latest result summary |
| `POST /scenarios/{id}/run` | `ScenarioRunRequest` | `ScenarioResult` with allocations, routes, costs and KPIs |
| `GET /scenarios/{id}/report.csv` | none | downloadable CSV |
| `GET /scenarios/{id}/report.pdf` | none | downloadable PDF |

`SuitabilityRequest` contains facility type, criterion weights, hard-exclusion configuration and optional candidate IDs. `SuitabilityResult` includes model version, data manifest references, scoring assumptions, exclusions, raw/normalized criterion values, weighted contributions, total score and rank. Coordinates are longitude/latitude; all buffers and distances are explicitly specified in metres and evaluated in the configured projected CRS. AHP pairwise matrices are validated as reciprocal positive matrices; responses include principal eigenvalue, consistency index/ratio and a warning if consistency is unacceptable.

## SQLite schema proposal

- `dataset(id, name, kind, source, source_year, licence, crs, status, synthetic, assumptions_json, imported_at, validation_json)`
- `scenario(id, name, description, facility_type, budget, settings_json, created_at, updated_at)`
- `scenario_dataset(scenario_id, dataset_id, role)`
- `criteria_model(id, scenario_id, facility_type, criteria_json, pairwise_matrix_json, weights_json, consistency_ratio, version)`
- `candidate_result(id, scenario_id, run_id, candidate_id, rank, score, excluded, reasons_json, contributions_json)`
- `allocation(id, scenario_id, run_id, demand_id, facility_id, quantity, route_distance_m, transport_cost)`
- `scenario_run(id, scenario_id, status, assumptions_json, kpis_json, started_at, completed_at, error)`

Geometry belongs in GeoPackage rather than SQLite JSON columns. Foreign keys are enabled; run outputs are immutable by `run_id` so scenario comparisons remain reproducible.

## Decision model and integrity rules

Collection centres and dismantling facilities have separate criteria and weights. The workflow first applies explicit hard exclusions, then normalizes eligible criteria, computes a weighted sum, and returns each contribution and exclusion reason. AHP derives weights and reports consistency; users can inspect and edit weights. Selection/allocation respects capacity and budget constraints. Road routing is based on a documented graph input; when only synthetic roads exist, route/cost outputs are labelled synthetic estimates. No regulatory buffer, official facility, ward, population, or demand value is assumed to be official unless provenance says so.

### Scenario optimization model

For each candidate facility subset, the engine creates a min-cost flow network. It chooses the subset with minimum total fixed cost, estimated transport cost, and configured unserved-demand penalty. Let `x[i,j]` be annual tonnes allocated from ward `i` to site `j`, `u[i]` unserved tonnes, and binary `y[j]` indicate an opened facility. Constraints are: `sum_j x[i,j] + u[i] = demand[i]`; `sum_i x[i,j] <= capacity[j] * y[j]`; `sum_j fixed_cost[j] * y[j] <= budget`; and `sum_j y[j] <= max_facilities`. Ineligible sites and disconnected ward/site pairs have no allocation arc. Subset enumeration makes the fixed-charge decision exact for up to 20 sites; NetworkX `network_simplex` exactly solves each allocation subproblem after demand is quantized to kilograms. The penalty makes partial service measurable while allowing the engine to return an allocation when full service is impossible.

Scenario API contracts live in `backend/app/api/scenario_schemas.py`. Runs are saved as immutable JSON snapshots in SQLite (`scenario_runs`); a group ID links baseline, optimized and future-demand runs for comparison. `GET /api/v1/scenarios/demo-inputs` only provides the explicitly synthetic fixture and refuses to generate those defaults for a non-synthetic imported dataset.

## Implementation sequence and review gate

1. **Scaffold (complete):** architecture, skeleton, pinned dependency manifests and demo-data schema/manifest.
2. **GIS and site selection (complete):** deterministic synthetic vector layers, local import/validation, separate facility criteria, AHP, hard exclusions, API schemas and ranked interactive map.
3. **Persistence and scenarios (complete):** SQLite immutable scenario runs, capacity/budget site-subset selection, demand allocation, and comparison endpoints.
4. **Routing and facility planning (complete):** road graph shortest paths with explicit point access connectors, cost assumptions, throughput/storage sizing and conceptual 2D layout.
5. **Comparison and reporting (complete):** baseline/optimized/future simulation, KPI views, saved-run comparison, provenance-rich CSV/PDF and layout PDF export.
6. **Verification (complete for implemented modules):** calculation/API/UI tests, seeded demo generator, setup guide and executable demo script. Full engineering, regulatory and field validation are outside this software verification.

After each implementation stage, run the stage's tests and startup/build checks and report exact commands and outcomes. Do not describe unimplemented modules as working.

## Test plan

- Unit tests: CRS conversion/metric distances; invalid dataset metadata; deterministic demo generation; AHP weights and consistency; exclusion boundaries; score normalization and explanations; capacity/budget feasibility; demand conservation; route costs; facility area arithmetic; report contents.
- API tests: schemas, validation errors, dataset endpoints, suitability ordering/explanations, scenario persistence, result retrieval and exports.
- Frontend tests: map layer/data states, ranking and exclusion explanations, scenario controls and returned map/KPI/ranking updates, facility assumption display.
- Acceptance checks: seeded fixture checksums, metric zone containment, oversized-envelope rejection, PDF/CSV content and saved-run comparison. Current Windows workspace tested with its installed virtual environment and Node dependencies; a clean dependency reinstall was not performed because network installation is restricted.

## Current status

The scaffold, GIS/site-selection workflow, scenario persistence, facility subset selection, road routing, conceptual facility sizing/layout, PDF/CSV reports, scenario comparison and the React workflow are implemented and tested. The local GeoJSON fixture and scenario defaults are deterministic synthetic estimates. Generated facility zones are conceptual area strips, not an engineering plan. No engineering approval, legal certification or measured environmental benefit is asserted.

## Verification record

Last verified in the project workspace:

- `backend\.venv\Scripts\python.exe -m pytest tests/backend -q -p no:cacheprovider` — 22 passed (backend tests require normal Windows temp-directory access).
- From `backend`: `.venv\Scripts\ruff.exe check app ..\tests\backend` — passed.
- From `frontend`: `npm test -- --run` — 4 passed.
- From `frontend`: `npm run build` — passed.
- `scripts/demo.ps1` against a live local Uvicorn server — passed; three scenario runs and PDF/CSV/layout-PDF downloads returned successfully.

The backend test run emits one Starlette/httpx TestClient deprecation warning; it does not affect the passing tests.

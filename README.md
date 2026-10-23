# Bengaluru E-Waste GIS Facility Planner

An explainable GIS planning demo. The bundled fixture is entirely synthetic: it does not represent official Bengaluru boundaries, roads, facilities, population, environmental data, or observed waste generation.

## Run locally

Backend (Python 3.12+):

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Frontend (Node 22+):

```powershell
cd frontend
npm install
npm run dev
```

Open the Vite URL printed by `npm run dev`. The API docs are at `http://localhost:8000/docs`. Set `VITE_API_ROOT` if the API is hosted elsewhere. To load local vector data instead of the demo, set `EWASTE_LAYER_DIR` to a directory containing `wards.geojson`, `roads.geojson`, `constraints.geojson`, and `candidates.geojson`, plus its provenance `manifest.json`; `EWASTE_MANIFEST` can point to the manifest explicitly. For other formats supported by GeoPandas, set individual `EWASTE_WARDS_PATH`, `EWASTE_ROADS_PATH`, `EWASTE_CONSTRAINTS_PATH`, and `EWASTE_CANDIDATES_PATH` variables and set `EWASTE_MANIFEST`. Every layer needs an embedded CRS.

Run backend tests from `backend` with `.venv\Scripts\python.exe -m pytest ..\tests\backend`; frontend checks run from `frontend` with `npm test` and `npm run build`.

### Seeded synthetic demo

The bundled vector fixture is tagged `synthetic_demo`. Its manifest records seed `20260617`; the data generator uses fixed coordinates and attributes without random sampling, so the same fixture is written each time:

```powershell
cd backend
.venv\Scripts\python.exe -m app.gis.demo_data
```

Start the API and UI in separate terminals using the commands above. Run `..\scripts\demo.ps1` from the repository root after the API is ready. It creates a baseline, optimized and +25% future scenario, then downloads a scenario PDF/CSV comparison and a conceptual layout PDF to `demo-output/`. The page's navigation links move between site selection, network scenarios, facility layout and reports.

## Current analytical workflow

`GET /api/v1/datasets/{wards|roads|constraints|candidates}/features` returns GeoJSON, and `POST /api/v1/suitability/evaluate` evaluates one facility type. The response contains scored GeoJSON, criterion directions and weights, AHP diagnostics (when a pairwise matrix is supplied), validation results and assumptions. `constraint_buffer_m` and `constraint_types` are user-configured hard exclusions; there are no baked-in regulatory distances. Metric buffer operations use EPSG:32643 and map responses use EPSG:4326.

Criteria use min-max normalization over the candidate set for the selected facility type. Benefit values increase suitability, cost values are reversed, and constant columns score 100 for every candidate. Excluded sites remain visible with reasons but do not receive an eligible rank. Equal scores are ordered by candidate ID for reproducible results.

## Facility and demand scenarios

`GET /api/v1/scenarios/demo-inputs` returns a clearly labelled synthetic demand/cost/capacity fixture only when the loaded manifest is `synthetic_demo`. For other datasets, provide verified values in each scenario request. Run scenarios with `POST /api/v1/scenarios/run`, retrieve immutable saved runs with `GET /api/v1/scenarios/{run_id}`, list them with `GET /api/v1/scenarios?group_id=...`, and compare runs with `POST /api/v1/scenarios/compare`.

The request accepts annual tonnes by ward, fixed facility costs, capacities, fixed-cost budget, maximum facility count, transport cost per tonne-kilometre, future growth, the selected facility type, and `input_data_status` (`official`, `estimated`, or `synthetic_demo`). Baseline runs must name their existing facilities; optimized runs select sites under the constraints; future-demand runs re-optimize after applying the growth input. The objective minimizes selected fixed costs, estimated transport costs, and a user-configurable penalty for unserved tonnes. `total_estimated_operating_cost` reports fixed plus transport costs; `optimization_objective_cost` also includes the unserved-demand penalty that drives the allocation choice. For each candidate facility subset, ward-to-site allocation is solved as an exact min-cost flow in NetworkX, with demand represented in 1 kg increments. The solver enumerates subsets and supports up to 20 candidate facilities. Demand conservation is returned as allocated plus unserved tonnes.

When the local road layer has valid linework, routes use shortest paths over a graph in EPSG:32643. Ward polygons are represented by their interior representative points. Origin and facility points connect to their nearest road vertices using explicit straight-line access connectors; these lengths are returned separately from road distance and are included in the estimated trip distance and cost. A disconnected route is unavailable; the analysis never substitutes direct point-to-point distance. The graph treats roads as undirected and does not model turns, travel time, or vehicle restrictions. `transport_distance_km` is the allocation-weighted average route length; `transport_tonne_km` is its allocated-tonnage sum. Results and all parameters, criterion weights, dataset version and GeoJSON candidate features are stored in local SQLite (`EWASTE_SCENARIO_DB` can override the path).

The map displays selected sites, eligibility and reasons, candidate scores, and tonnes allocated. Scenario cards show service coverage by demand volume, unserved demand, estimated operating cost, route distance and capacity utilization. Demo values and all outputs derived from them remain synthetic estimates.

## Facility design and reporting

`GET /api/v1/facility-design/defaults` returns editable demonstration assumptions. `POST /api/v1/facility-design/plan` calculates annual throughput (tonnes/day × operating days/year), storage capacity (tonnes/day × storage days), and process-zone areas from configurable square-metre factors. The layout places adjacent full-depth zones inside a rectangular envelope in local metres and returns 422 when the requested zones exceed that envelope. The SVG preview shows all six zone labels and dimensions. `POST /api/v1/facility-design/layout.pdf` exports the conceptual drawing.

The sizing factors are planning assumptions: receiving, inspection, dismantling and dispatch use m² per tonne/day; segregated storage uses m² per stored tonne; circulation is a fraction of the other zones. They are not building-design standards. The conceptual plan excludes structural design, fire protection, accessibility, utilities, setbacks, code checks and regulatory review.

`GET /api/v1/reports/{run_id}.pdf` and `.csv` export saved scenario snapshots with input assumptions, criterion weights, dataset provenance, candidate ranking/exclusions, selected facilities and capacity, demand allocations, transport costs/distances, KPI results, saved-run comparisons, validation checks and limitations. Reports state that the tool does not provide engineering approval, legal compliance certification or measured environmental benefits. Scenario runs use the dataset version and provenance captured when the run was created.

## Verification and known limitations

### Checks passed in this workspace

| Command | Result |
| --- | --- |
| From the repository root: `backend\.venv\Scripts\python.exe -m pytest tests/backend -q -p no:cacheprovider` | 22 passed; one Starlette/httpx deprecation warning |
| From `backend`: `.venv\Scripts\ruff.exe check app ..\tests\backend` | Passed |
| From `frontend`: `npm test -- --run` | 4 passed |
| From `frontend`: `npm run build` | Passed |
| With Uvicorn running: `scripts/demo.ps1` | Passed; created 3 scenarios and downloaded report/layout exports |

Backend coverage includes normalized suitability and AHP/exclusion rules, invalid geometry, deterministic rankings and fixture generation, route disconnection, facility budget/capacity/demand accounting, scenario persistence and comparison repeatability, facility area sizing and envelope rejection, plus PDF structure/content and CSV sections. Frontend tests cover candidate explanations, facility-type re-evaluation, edited network controls updating API requests/map/KPIs/rankings, and changed throughput recalculation. The reports use a built-in vector/text PDF writer and standard-library CSV, with no optional reporting dependency.

The facility arrangement is a conceptual area diagram, not a construction drawing. Scenario routing uses an undirected graph and explicit straight-line road-access connectors; it does not model travel time, turns, congestion or vehicle limits. Exact facility subset enumeration is intended for at most 20 candidate facilities, and demand allocation is quantized to 1 kg. Synthetic/estimated inputs must be replaced with verified data before real planning use. GIS and scenario outputs do not establish regulatory suitability or environmental outcomes.

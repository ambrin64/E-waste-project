# Technical Guide (Plain Language)

This guide describes how the Bengaluru E-Waste GIS Facility Planner is put together. It is written for readers who want to understand the technology without needing to know every library in advance.

## The application in one picture

```text
Web browser
React + TypeScript + Leaflet
        | JSON requests and responses
FastAPI backend
GIS + suitability + network allocation + facility sizing + reports
        |                         |
Local spatial files          Local SQLite scenario records
```

The browser collects inputs and displays maps, rankings, scenario results, and layouts. The Python backend performs the calculations and returns the results. Keeping the calculations in the backend makes the API usable independently of the screen and lets tests check the same business rules directly.

## Main technologies

| Part | Technology | What it does here |
| --- | --- | --- |
| User interface | React, TypeScript, Vite | Builds the interactive web application and checks UI code types. |
| Map | Leaflet and React-Leaflet | Displays spatial layers and candidate results. |
| Web API | FastAPI and Pydantic | Receives JSON inputs, validates their shape and allowed values, and returns JSON or downloadable files. |
| Spatial processing | GeoPandas, Shapely, PyProj | Reads vector layers, checks and transforms geometry, and performs metric distance/buffer operations. |
| Tabular processing | Pandas | Organizes and scores candidate attributes. |
| Road routing and allocation | NetworkX | Finds paths in the road graph and solves demand allocation for a selected facility set. |
| Local persistence | SQLite | Stores scenario runs and their input/result snapshots. |
| Reports | Project PDF/CSV exporters | Creates PDF and CSV downloads without requiring a separate reporting service. |
| Automated checks | pytest, Vitest, Testing Library | Checks backend calculations/API behavior and frontend interactions. |

## Where the code lives

- `frontend/src/app/` contains the main page and its UI tests.
- `frontend/src/features/map/` contains map rendering.
- `frontend/src/features/facility/` contains the facility designer UI.
- `frontend/src/lib/api.ts` sends requests to the backend and handles API errors.
- `frontend/src/types/api.ts` describes the data structures used by the frontend.
- `backend/app/api/` contains API routes and Pydantic request/response models.
- `backend/app/gis/` loads and validates spatial input data and creates the seeded demo layers.
- `backend/app/decision/` normalizes suitability criteria, calculates scores, applies exclusions, and handles AHP weights.
- `backend/app/routing/` builds road-graph route calculations.
- `backend/app/optimization/` chooses candidate facility sets and allocates ward demand.
- `backend/app/facility/` calculates facility areas and places conceptual zones.
- `backend/app/db/` stores and retrieves saved scenario runs.
- `backend/app/reporting/` prepares scenario and facility PDF/CSV exports.
- `tests/backend/` contains backend tests; `frontend/src/app/App.test.tsx` contains the current frontend tests.

## Data and map flow

The demo layers are stored under `data/demo/` as local spatial files, alongside manifests that identify the dataset as synthetic and record its provenance. The API loads the layers, checks required fields, coordinate reference systems, geometry, and data coverage, then serves map features as GeoJSON.

GeoJSON coordinates sent to the browser use longitude and latitude (WGS 84). Distance, buffer, and area calculations use projected coordinates in the GIS services. A dataset should include its actual CRS; the application should not infer one silently.

Local data can be supplied using the environment variables documented in `README.md`. Imported data must have a matching provenance manifest. Official, estimated, and synthetic data should remain distinguishable in inputs and results.

## Suitability calculation

Collection centres and dismantling facilities use separate criteria. The service converts each criterion to a 0–100 scale. Benefit criteria increase with the measured value; cost criteria are reversed so that lower cost can mean higher suitability. A constant-valued criterion receives the same normalized score for all candidates.

Optional AHP pairwise comparisons produce criteria weights and a consistency report. Hard exclusions are checked separately from suitability scoring. This is why a candidate may show a score while still being marked excluded: the score supports comparison, but exclusion means it is not eligible for selection.

## Network scenarios

The scenario endpoint accepts demand by ward, fixed costs, capacities, a budget, a maximum facility count, transport-cost assumptions, facility type, and scenario settings. It can run a baseline, an optimized plan, or a future-demand case.

The current solver enumerates candidate facility subsets, then uses a NetworkX minimum-cost-flow calculation to allocate demand for each subset. It enforces facility capacities, budget, and facility count. Demand is quantized to 1 kg for allocation. The exact subset search supports up to 20 candidates; a larger statewide or citywide candidate set would require a different scaling approach.

When valid road data are available, route calculations use the road graph. Site/ward connections to the nearest road vertices are explicit access-distance estimates. A disconnected route is unavailable; it is not silently replaced with a straight-line ward-to-site distance. The road model does not include traffic, turn restrictions, vehicle limits, or travel time.

Scenario runs are saved in SQLite with their inputs, dataset version, criteria weights, and results. A group ID links baseline, optimized, and future-demand runs for comparison. The saved snapshot lets reports describe what was used for that run.

## Facility sizing and layout

The facility API calculates:

- Annual throughput = daily throughput × operating days per year.
- Storage quantity = daily throughput × storage duration.
- Receiving, inspection, dismantling, and dispatch area from editable area-per-throughput factors.
- Segregated storage area from an editable area-per-stored-tonne factor.
- Circulation area from the configured fraction of the process-zone area.

The area-based layout represents each zone as a square whose side is the square root of its calculated area. It places the zones in one row when they fit, otherwise it attempts a deterministic two-row arrangement. These dimensions and positions are a conceptual visualization convention. They are not engineering standards. If the requested zones do not fit the chosen packing convention and plot, the API reports the fit constraint rather than shrinking the zones.

The full-plot map preserves the plot scale. An enlarged detail view and an additional PDF page improve zone legibility while retaining the same metre coordinates and dimensions. Circulation is represented as one conceptual zone; it does not depict distributed aisles or access routes. Unallocated area is the configured plot area minus all five process areas and the circulation area, counted once.

## Important API endpoints

All paths below are under `/api/v1`:

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Check that the API is responding. |
| `GET /datasets/{layer}/features` | Get a spatial layer as GeoJSON. |
| `POST /suitability/evaluate` | Score and rank candidate sites, with exclusions and explanations. |
| `GET /scenarios/demo-inputs` | Get synthetic scenario inputs when the loaded dataset is the labelled demo dataset. |
| `POST /scenarios/run` | Run and save one network scenario. |
| `GET /scenarios/{run_id}` | Retrieve a saved run. |
| `POST /scenarios/compare` | Compare saved runs. |
| `GET /facility-design/defaults` | Get editable facility-sizing assumptions. |
| `POST /facility-design/plan` | Calculate and return a conceptual layout. |
| `POST /facility-design/layout.pdf` | Download the conceptual facility layout PDF. |
| `GET /reports/{run_id}.pdf` or `.csv` | Download a saved scenario report. |

The automatically generated OpenAPI page is available at `http://localhost:8000/docs` while the API is running.

## Run locally on Windows PowerShell

Start the backend in one terminal:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Start the frontend in a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open the local Vite URL printed in the frontend terminal. API requests default to `http://localhost:8000/api/v1`; `VITE_API_ROOT` can override it.

## Run checks

From the project root:

```powershell
backend\.venv\Scripts\python.exe -m pytest -q
```

From `frontend`:

```powershell
npm test -- --run
npm run build
```

The backend tests cover GIS validation, normalization, AHP consistency, hard exclusions, deterministic suitability rankings, network budgets/capacities/demand accounting, route behavior, scenario storage/comparison, facility-area/layout constraints, and report content. The frontend tests cover rankings and exclusion messages, scenario requests/results, layout recalculation, and Reports navigation.

## Known limits

- The bundled Bengaluru data and scenario defaults are synthetic, not official or measured.
- The facility layout is conceptual and does not include structural, fire, access, utilities, setbacks, or code design.
- Circulation is a single conceptual zone, not a distributed aisle/access model.
- Roads are modeled as an undirected graph; route access connectors are estimates.
- Exact subset optimization has a 20-candidate limit.
- The current application is configured around one Bengaluru dataset, not a multi-state dataset manager.


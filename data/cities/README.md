# City GIS data included with the planner

The ward maps are local, source-attributed data. The existing suitability candidates, roads, constraints, and scenario inputs are still a separate synthetic Bengaluru demonstration dataset. The app intentionally does not score Mumbai or infer e-waste demand from population.

## Greater Bengaluru

- Boundary: 369 Greater Bengaluru Authority wards notified in 2025, republished by OpenCity / Oorvani Foundation. [Dataset catalogue](https://bharatlas.com/view/wards_bengaluru_gba), licence ODbL 1.0.
- Population attributes: 2011 Census values included in the GBA 2025 map. These are historical and not a current population estimate or e-waste demand. Current 2025 ward IDs do not establish a verified crosswalk to every historical census geography.
- The downloaded source coordinates put latitude in GeoJSON's longitude slot. `scripts/prepare_city_data.py` detects the city extent and swaps the axes in normalized output; source files remain unchanged. Eight source geometries were also invalid and are repaired with Shapely `make_valid`, preserving polygon components. The exact repaired IDs and axis correction are listed in `layers/validation.json`.

## Greater Mumbai (BMC)

- Boundary: 24 administrative wards from OpenCity / Oorvani Foundation. [Dataset catalogue](https://bharatlas.com/view/wards_mumbai), licence ODbL 1.0. The catalogue does not state the boundary vintage. The downloaded source also had latitude and longitude reversed; normalized GeoJSON is axis-corrected and the original is retained.
- Population: BMC's [Civic Diary 2025](https://portal.mcgm.gov.in/irj/portal/anonymous/qlCivicDemographics) reports ward-wise mid-year population estimates for 2023. The app sums the 24 ward entries (13,014,389); the same BMC table's aggregate is 13,014,390, a one-person discrepancy retained and disclosed in the manifest.
- Population is not a proxy for measured e-waste without an explicit, validated conversion model.

## Rebuild normalized ward layers

The committed `wards_source.geojson` files are the unmodified downloaded inputs. From the repository root run:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_city_data.py
```

The script checks feature count, unique ward IDs, geometry presence/validity and geographic coordinate bounds, then writes normalized `layers/wards.geojson` and `layers/validation.json`. It does not download newer data, invent missing data or alter the original source files.

## Current analysis coverage

The city selector currently displays sourced ward boundaries and available population attributes for both cities. Bengaluru suitability and network simulation still use the clearly marked synthetic demo candidate, road, constraint and demand layers. Mumbai has no candidate parcels, validated road graph, environmental constraints or ward-level e-waste-demand observations in this package, so those analyses are disabled there.

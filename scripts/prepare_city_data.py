"""Normalize the committed, source-attributed city ward GeoJSON files.

The source files are downloaded from the URLs recorded in each city manifest.
This script performs no geocoding, population projection, or random generation.
"""

from __future__ import annotations

import json
from pathlib import Path

from shapely import make_valid, transform as transform_coordinates
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]
CITY_ROOT = ROOT / "data" / "cities"
CITY_EXTENTS = {
    "bengaluru": (77.2, 12.6, 78.0, 13.4),
    "mumbai": (72.6, 18.7, 73.2, 19.4),
}

MUMBAI_POPULATION_2023 = {
    "A": 193520, "B": 133142, "C": 173800, "D": 362812, "E": 411366,
    "F/S": 377567, "F/N": 553355, "G/S": 395115, "G/N": 626578,
    "H/E": 582857, "H/W": 321722, "K/E": 861762, "K/W": 783107,
    "P/S": 484816, "P/N": 984647, "R/S": 723007, "R/C": 588006,
    "R/N": 451199, "L": 943703, "M/E": 844854, "M/W": 430829,
    "N": 651487, "S": 777977, "T": 357161,
}


def normalize(city_id: str) -> int:
    directory = CITY_ROOT / city_id
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    source_path = directory / "layers" / "wards_source.geojson"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("type") != "FeatureCollection":
        raise ValueError(f"{source_path} is not a GeoJSON FeatureCollection")

    extent = CITY_EXTENTS[city_id]
    source_bounds = [shape(feature["geometry"]).bounds for feature in source["features"] if feature.get("geometry")]
    bounds = (min(item[0] for item in source_bounds), min(item[1] for item in source_bounds),
              max(item[2] for item in source_bounds), max(item[3] for item in source_bounds))

    def fits(bounds_to_check: tuple[float, float, float, float]) -> bool:
        min_x, min_y, max_x, max_y = bounds_to_check
        min_lon, min_lat, max_lon, max_lat = extent
        return min_lon <= min_x and max_x <= max_lon and min_lat <= min_y and max_y <= max_lat

    coordinates_reversed = not fits(bounds) and fits((bounds[1], bounds[0], bounds[3], bounds[2]))
    if not fits(bounds) and not coordinates_reversed:
        raise ValueError(f"Source coordinates for {city_id} do not fall within its expected geographic extent: {bounds}")

    output = []
    seen: set[str] = set()
    repaired_ids: list[str] = []
    for feature in source["features"]:
        properties = dict(feature.get("properties") or {})
        if city_id == "mumbai":
            ward_id = " ".join(str(properties.get("NAME2") or properties.get("Name", "")).split()).upper()
            label = ward_id
            population = MUMBAI_POPULATION_2023.get(ward_id)
            population_year = 2023 if population is not None else None
            population_source = "Brihanmumbai Municipal Corporation, Civic Diary 2025 (mid-year estimate for 2023)" if population is not None else None
        elif city_id == "bengaluru":
            ward_number = str(properties.get("ward_id", "")).strip()
            corporation_id = str(properties.get("corporation_id", "")).strip()
            ward_id = f"{corporation_id}-{ward_number}" if corporation_id and ward_number else ward_number
            label = str(properties.get("ward_name", ward_id)).strip()
            try:
                population = int(float(properties["TOT_P"]))
            except (KeyError, TypeError, ValueError):
                population = None
            population_year = 2011 if population is not None else None
            population_source = "2011 Census population attribute included in the GBA 2025 ward map" if population is not None else None
        else:
            raise ValueError(f"No normalization rules for {city_id}")

        if not ward_id or ward_id in seen:
            raise ValueError(f"Missing or duplicate ward identifier {ward_id!r} in {source_path}")
        seen.add(ward_id)
        geometry = feature.get("geometry")
        if not geometry:
            raise ValueError(f"Ward {ward_id} has no geometry")
        polygon = shape(geometry)
        if polygon.is_empty:
            raise ValueError(f"Ward {ward_id} has an empty geometry")
        if coordinates_reversed:
            # These downloaded GeoJSONs encode x=latitude, y=longitude despite
            # GeoJSON requiring x=longitude, y=latitude.
            polygon = transform_coordinates(polygon, lambda coordinates: coordinates[..., ::-1])
        if not polygon.is_valid:
            polygon = make_valid(polygon)
            if isinstance(polygon, GeometryCollection):
                polygon = unary_union([part for part in polygon.geoms if isinstance(part, (Polygon, MultiPolygon))])
            if polygon.is_empty or not polygon.is_valid or polygon.geom_type not in {"Polygon", "MultiPolygon"}:
                raise ValueError(f"Ward {ward_id} could not be repaired into a valid polygon")
            repaired_ids.append(ward_id)
        min_x, min_y, max_x, max_y = polygon.bounds
        if not fits((min_x, min_y, max_x, max_y)):
            raise ValueError(f"Ward {ward_id} is outside the expected longitude/latitude extent after normalization")
        geometry = mapping(polygon)
        properties.update({
            "ward_id": ward_id,
            **({"corporation_ward_number": ward_number} if city_id == "bengaluru" else {}),
            "label": label,
            "data_status": "sourced_open_data",
            "synthetic": False,
            "population_estimate": population,
            "population_year": population_year,
            "population_source": population_source,
            "population_is_e_waste_demand": False,
        })
        output.append({"type": "Feature", "id": ward_id, "geometry": geometry, "properties": properties})

    expected = manifest["boundary"]["feature_count"]
    if len(output) != expected:
        raise ValueError(f"Expected {expected} wards, got {len(output)} for {city_id}")
    target = directory / "layers" / "wards.geojson"
    target.write_text(json.dumps({"type": "FeatureCollection", "features": output}, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    report = {
        "source_file": source_path.name,
        "output_crs": "EPSG:4326",
        "feature_count": len(output),
        "unique_ward_ids": len(seen),
        "source_coordinates_reversed": coordinates_reversed,
        "coordinate_processing": "Swapped source x/y to longitude/latitude before writing GeoJSON" if coordinates_reversed else "Source already used longitude/latitude",
        "invalid_source_geometries_repaired": repaired_ids,
        "repair_method": "Shapely make_valid; polygon components retained for map display; source geometry file remains unchanged",
    }
    (directory / "layers" / "validation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return len(output)


if __name__ == "__main__":
    for city in ("bengaluru", "mumbai"):
        print(f"{city}: normalized {normalize(city)} wards")

"""Generate fixed synthetic vector layers for repeatable local demonstrations."""

from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon

ROOT = Path(__file__).resolve().parents[3]
DEMO_DIR = ROOT / "data" / "demo"
OUTPUT_DIR = DEMO_DIR / "layers"
CRS = "EPSG:4326"


def build_demo_layers(output_dir: Path = OUTPUT_DIR) -> dict[str, Path]:
    """Write stable, labelled artificial Bengaluru-like shapes; no randomness used."""
    output_dir.mkdir(parents=True, exist_ok=True)
    wards = gpd.GeoDataFrame([
        {"ward_id": f"SYN-W{i}", "label": f"Synthetic planning zone {i}",
         "data_status": "synthetic_demo", "synthetic": True,
         "geometry": Polygon([(77.50 + i * .02, 12.94), (77.52 + i * .02, 12.94),
                              (77.52 + i * .02, 12.96), (77.50 + i * .02, 12.96)])}
        for i in range(5)
    ], crs=CRS)
    roads = gpd.GeoDataFrame([
        {"road_id": f"SYN-R{i}", "road_class": "synthetic arterial", "data_status": "synthetic_demo",
         "synthetic": True, "geometry": LineString([(77.50 + i * .02, 12.95), (77.52 + i * .02, 12.95)])}
        for i in range(5)
    ], crs=CRS)
    constraints = gpd.GeoDataFrame([
        {"constraint_id": "SYN-E1", "constraint_type": "synthetic_waterbody", "data_status": "synthetic_demo",
         "synthetic": True, "geometry": Polygon([(77.535, 12.948), (77.538, 12.948), (77.538, 12.952), (77.535, 12.952)])},
        {"constraint_id": "SYN-E2", "constraint_type": "synthetic_sensitive_use", "data_status": "synthetic_demo",
         "synthetic": True, "geometry": Polygon([(77.575, 12.948), (77.578, 12.948), (77.578, 12.952), (77.575, 12.952)])},
    ], crs=CRS)
    # Deliberate values make the fixture reproducible and easy to inspect.
    values = [
        ("SYN-C01", "collection_centre", 92, 82, 38, 12, 65, 77.505, 12.945),
        ("SYN-C02", "collection_centre", 78, 91, 55, 8, 70, 77.515, 12.955),
        ("SYN-C03", "collection_centre", 86, 74, 31, 16, 58, 77.525, 12.945),
        ("SYN-C04", "collection_centre", 65, 88, 43, 9, 62, 77.545, 12.955),
        ("SYN-C05", "collection_centre", 73, 68, 25, 11, 55, 77.555, 12.945),
        ("SYN-C06", "collection_centre", 90, 78, 62, 7, 80, 77.565, 12.955),
        ("SYN-D01", "dismantling_facility", 55, 76, 48, 15, 94, 77.585, 12.945),
        ("SYN-D02", "dismantling_facility", 64, 84, 65, 10, 88, 77.595, 12.955),
    ]
    candidates = gpd.GeoDataFrame([
        {"candidate_id": row[0], "candidate_type": row[1], "demand_access": row[2],
         "road_access": row[3], "land_cost": row[4], "environmental_risk": row[5],
         "industrial_compatibility": row[6], "hard_allowed": row[0] != "SYN-C02",
         "data_status": "synthetic_demo", "synthetic": True,
         "geometry": Point(row[7], row[8])}
        for row in values
    ], crs=CRS)
    layers = {"wards": wards, "roads": roads, "constraints": constraints, "candidates": candidates}
    paths = {}
    for name, frame in layers.items():
        path = output_dir / f"{name}.geojson"
        frame.to_file(path, driver="GeoJSON")
        paths[name] = path
    manifest = json.loads((DEMO_DIR / "manifest.json").read_text(encoding="utf-8"))
    manifest.update({"layers": {key: value.name for key, value in paths.items()},
                     "generation_seed": 20260617,
                     "generation_method": "fixed deterministic coordinates and attributes; no random sampling",
                     "coordinate_reference_system": CRS})
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return paths


if __name__ == "__main__":
    for layer_name, layer_path in build_demo_layers().items():
        print(f"Wrote synthetic {layer_name}: {layer_path}")

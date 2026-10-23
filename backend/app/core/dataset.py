"""Cached local dataset access, configurable by environment variables."""

import os
from functools import lru_cache
from pathlib import Path

from app.gis.demo_data import DEMO_DIR, build_demo_layers
from app.gis.pipeline import DatasetBundle, load_dataset


@lru_cache(maxsize=1)
def get_dataset() -> DatasetBundle:
    layer_names = ("wards", "roads", "constraints", "candidates")
    demo_default = "EWASTE_LAYER_DIR" not in os.environ and not any(
        f"EWASTE_{name.upper()}_PATH" in os.environ for name in layer_names)
    layer_dir = Path(os.environ.get("EWASTE_LAYER_DIR", DEMO_DIR / "layers"))
    manifest_path = Path(os.environ.get("EWASTE_MANIFEST", layer_dir / "manifest.json"))
    if (not demo_default and "EWASTE_MANIFEST" not in os.environ
            and ("EWASTE_LAYER_DIR" not in os.environ or not manifest_path.is_file())):
        raise ValueError("Custom spatial data requires an explicit provenance manifest (EWASTE_MANIFEST)")
    layer_paths = {name: Path(os.environ.get(f"EWASTE_{name.upper()}_PATH", layer_dir / f"{name}.geojson"))
                   for name in layer_names}
    if demo_default and not all(path.is_file() for path in layer_paths.values()):
        build_demo_layers(layer_dir)
    return load_dataset(layer_paths, manifest_path)


def clear_dataset_cache() -> None:
    get_dataset.cache_clear()

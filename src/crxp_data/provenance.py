"""Build provenance: capture the library + geospatial-stack versions that determine numeric output.

Written to exports/crxp/data/provenance.json on every build so a published data product records
exactly which versions produced it (ACS/zonal numbers can shift across GDAL/PROJ/exactextract releases).
"""
from __future__ import annotations
import json
import platform
import importlib.metadata as md
from pathlib import Path

_PKGS = ["pandas", "pyarrow", "duckdb", "requests", "PyYAML",
         "geopandas", "shapely", "pyproj", "rasterio", "exactextract"]


def _ver(pkg: str) -> str:
    try:
        return md.version(pkg)
    except Exception:  # noqa: BLE001
        return "unknown"


def _geospatial_stack() -> dict:
    out = {}
    try:
        import rasterio
        out["GDAL"] = getattr(rasterio, "__gdal_version__", "unknown")
    except Exception:  # noqa: BLE001
        out["GDAL"] = "unknown"
    try:
        import pyproj
        out["PROJ"] = pyproj.proj_version_str
    except Exception:  # noqa: BLE001
        out["PROJ"] = "unknown"
    return out


def collect(build_date: str | None = None) -> dict:
    """Return a provenance dict (no clock access unless build_date is passed)."""
    prov = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": {p: _ver(p) for p in _PKGS},
        "geospatial": _geospatial_stack(),
    }
    if build_date:
        prov["build_date"] = build_date
    return prov


def write(target_dir: Path, build_date: str | None = None) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "provenance.json"
    path.write_text(json.dumps(collect(build_date), indent=2))
    return path

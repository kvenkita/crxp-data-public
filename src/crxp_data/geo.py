"""Geometry helpers: tract centroids for spatial weights (reuses the app's tract geojson)
and 2020 tract land area (for density-style indicators)."""
from __future__ import annotations
import json
from pathlib import Path
from .config import ROOT

DEFAULT_TRACTS = ROOT.parent / "crxp" / "static" / "data" / "geo" / "tracts.geojson"
LAND_CSV = ROOT / "data" / "tract_land_area.csv"
_SQM_PER_SQMI = 2_589_988.110336


def load_tract_centroids(path: Path | None = None) -> dict[str, tuple[float, float]]:
    """Return {geoid: (lng, lat)} representative points for all tracts.

    Uses shapely's representative_point(), which is guaranteed to fall INSIDE the polygon — unlike a
    bounding-box midpoint, which for L-shaped / crescent / coastal tracts can land outside the tract and
    distort the k-nearest-neighbour graph that feeds the LISA spatial weights."""
    from shapely.geometry import shape
    fc = json.loads(Path(path or DEFAULT_TRACTS).read_text())
    out = {}
    for f in fc["features"]:
        gid = str(f.get("id") or f["properties"]["geoid"])
        pt = shape(f["geometry"]).representative_point()
        out[gid] = (pt.x, pt.y)
    return out


def load_tracts_gdf(crs=5070, path: Path | None = None):
    """Load the 2020 tracts as a GeoDataFrame (geoid + geometry), reprojected to `crs`."""
    import geopandas as gpd
    gdf = gpd.read_file(path or DEFAULT_TRACTS)
    if "geoid" not in gdf.columns:
        gdf["geoid"] = gdf["id"] if "id" in gdf.columns else gdf.index.astype(str)
    gdf["geoid"] = gdf["geoid"].astype(str)
    return gdf.to_crs(crs)[["geoid", "geometry"]]


def load_land_area(region: dict) -> dict[str, float]:
    """Return {geoid: land area in sq miles} for 2020 tracts (cached to data/; built from
    the Census 2020 tract relationship files)."""
    import pandas as pd
    if not LAND_CSV.exists():
        import io
        import requests
        from .harmonize import REL_URL
        county_fips = {c["fips"] for c in region["counties"]}
        rows = {}
        for ss in sorted({c["fips"][:2] for c in region["counties"]}):
            df = pd.read_csv(io.StringIO(requests.get(REL_URL.format(ss=ss), timeout=180).text), sep="|", dtype=str)
            for _, r in df.iterrows():
                t20 = r["GEOID_TRACT_20"]
                if t20[:5] in county_fips:
                    rows[t20] = float(r["AREALAND_TRACT_20"]) / _SQM_PER_SQMI
        LAND_CSV.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame([{"geoid": k, "aland_sqmi": v} for k, v in sorted(rows.items())]).to_csv(LAND_CSV, index=False)
    df = pd.read_csv(LAND_CSV, dtype={"geoid": str})
    return dict(zip(df["geoid"], df["aland_sqmi"]))

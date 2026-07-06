"""NLCD raster source: clip region rasters from the MRLC WCS (auth-free) and compute
tract-level zonal statistics (area-weighted, exact pixel fractions via exactextract).

Two stats:
  - classfrac: share of a tract's (non-nodata) area in a set of NLCD land-cover classes
  - mean:      area-weighted mean of a continuous raster (e.g. % impervious)

NLCD is wall-to-wall classification, so these carry no sampling margin of error.
"""
from __future__ import annotations
import requests
import pandas as pd
import rasterio
from rasterio.windows import from_bounds
from pyproj import Transformer
from exactextract import exact_extract
from ..config import ROOT
from ..geo import load_tracts_gdf

WCS = "https://www.mrlc.gov/geoserver/mrlc_download/wcs"
RDIR = ROOT / "data" / "raster"


def _bbox_5070(region: dict, pad: float = 2000.0):
    """Region bounding box in EPSG:5070 (NLCD Albers), padded by `pad` metres."""
    fips = {c["fips"] for c in region["counties"]}  # noqa: F841 (region implied by tract set)
    b = load_tracts_gdf(5070).total_bounds
    return b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad


def fetch_clip(coverage: str, region: dict) -> str:
    """Download (once) a region-clipped GeoTIFF for an MRLC coverage; cache under data/raster/."""
    RDIR.mkdir(parents=True, exist_ok=True)
    out = RDIR / f"{coverage}.tif"
    if out.exists():
        return str(out)
    xmin, ymin, xmax, ymax = _bbox_5070(region)
    url = (f"{WCS}?service=WCS&version=2.0.1&request=GetCoverage&coverageId={coverage}"
           f"&format=image/geotiff&subset=X({xmin},{xmax})&subset=Y({ymin},{ymax})")
    print(f"      WCS clip {coverage} ...")
    r = requests.get(url, timeout=600)
    if r.content[:4] not in (b"II*\x00", b"MM\x00*"):
        raise RuntimeError(f"WCS {coverage}: {r.status_code} {r.content[:200]}")
    # atomic write: stream to .part then rename, so an interrupted download never leaves a
    # truncated .tif that later runs would treat as a valid cache.
    tmp = out.with_suffix(out.suffix + ".part")
    tmp.write_bytes(r.content)
    tmp.replace(out)
    return str(out)


def _vsi_path(spec: dict, year: int) -> str:
    """Build a GDAL path to a per-year GeoTIFF inside a (possibly nested) local zip."""
    outer = RDIR / spec["outer_zip"]
    if spec.get("inner_zip_template"):  # zip-of-zips (e.g. NLCD TCC bundle)
        inner = spec["inner_zip_template"].format(year=year)
        tif = spec["tif_template"].format(year=year)
        return f"/vsizip/{{/vsizip/{{{outer}}}/{inner}}}/{tif}"
    tif = spec["tif_template"].format(year=year)
    return f"/vsizip/{{{outer}}}/{tif}"


def _local_clip(spec: dict, year: int):
    """Clip a (large, possibly nested-zip) local raster to the region once; cache the small clip.
    Returns (clip_path, tracts_gdf_in_raster_crs)."""
    clip = RDIR / f"{spec['product']}_{year}_clip.tif"
    if not clip.exists():
        with rasterio.open(_vsi_path(spec, year)) as ds:
            gdf = load_tracts_gdf(ds.crs)
            minx, miny, maxx, maxy = gdf.total_bounds
            win = from_bounds(minx - 1000, miny - 1000, maxx + 1000, maxy + 1000, ds.transform)
            a = ds.read(1, window=win)
            prof = ds.profile.copy()
            prof.update(height=a.shape[0], width=a.shape[1], transform=ds.window_transform(win),
                        driver="GTiff", compress="deflate")
        with rasterio.open(clip, "w", **prof) as dst:
            dst.write(a, 1)
    with rasterio.open(clip) as ds:
        return str(clip), load_tracts_gdf(ds.crs)


def fetch_indicator(region: dict, indicator: dict) -> pd.DataFrame:
    spec = indicator["raster"]
    years, stat = spec["years"], spec["stat"]

    # local nested-zip / file source (e.g. NLCD Tree Canopy Cover) — clip once, then zonal
    if spec.get("outer_zip"):
        frames = []
        for y in years:
            clip, gdf = _local_clip(spec, y)
            res = exact_extract(clip, gdf, ["mean"], include_cols=["geoid"], output="pandas")
            frames.append(pd.DataFrame([
                {"geoid": r.geoid, "year": y, "value": (round(r.mean, 4) if r.mean == r.mean else None), "moe": None}
                for r in res.itertuples()
            ]))
        return pd.concat(frames, ignore_index=True)

    tmpl = spec["coverage_template"]
    gdf = load_tracts_gdf(5070)
    frames = []
    for y in years:
        path = fetch_clip(tmpl.format(year=y), region)
        if stat == "classfrac":
            classes = {int(c) for c in spec["classes"]}
            res = exact_extract(path, gdf, ["unique", "frac"], include_cols=["geoid"], output="pandas")
            rows = []
            for r in res.itertuples():
                u, f = r.unique, r.frac
                pct = sum(fi for ui, fi in zip(u, f) if int(ui) in classes) * 100.0
                rows.append({"geoid": r.geoid, "year": y, "value": round(pct, 4), "moe": None})
        elif stat == "mean":
            res = exact_extract(path, gdf, ["mean"], include_cols=["geoid"], output="pandas")
            rows = [{"geoid": r.geoid, "year": y,
                     "value": (round(r.mean, 4) if r.mean == r.mean else None), "moe": None}
                    for r in res.itertuples()]
        else:
            raise ValueError(f"unknown raster stat {stat!r}")
        frames.append(pd.DataFrame(rows))
    return pd.concat(frames, ignore_index=True)

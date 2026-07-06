"""VIIRS Nighttime Lights (EOG VNL V2) source — light-pollution indicator.

EOG downloads require a (free) account: we obtain an OAuth bearer token from
eogauth.mines.edu (env EOG_USERNAME / EOG_PASSWORD), list the annual directory, download
the masked annual GeoTIFF (gzipped), clip it to the region, and compute the area-weighted
mean radiance per tract (nW/cm2/sr). No sampling MOE.
"""
from __future__ import annotations
import os
import re
import requests
import pandas as pd
import rasterio
from rasterio.windows import from_bounds
from rasterio.io import MemoryFile
from exactextract import exact_extract
from ..config import ROOT
from ..geo import load_tracts_gdf

# EOG migrated to Keycloak realm 'eog' with PER-ACCOUNT client credentials.
TOKEN_URL = "https://eogauth.mines.edu/realms/eog/protocol/openid-connect/token"
# A browser User-Agent is required (the nginx edge 403s default agents).
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"}
BASE = "https://eogdata.mines.edu/nighttime_light/annual/{ver}/{year}/"
RDIR = ROOT / "data" / "raster"


def get_token() -> str:
    user, pw = os.environ.get("EOG_USERNAME"), os.environ.get("EOG_PASSWORD")
    if not (user and pw):
        raise RuntimeError("VIIRS needs EOG_USERNAME and EOG_PASSWORD in the environment "
                           "(free account at https://eogdata.mines.edu/products/register/).")
    # Default to Keycloak's built-in public 'admin-cli' client (direct grant, no secret);
    # override with EOG_CLIENT_ID/EOG_CLIENT_SECRET if you have per-account credentials.
    data = {"client_id": os.environ.get("EOG_CLIENT_ID", "admin-cli"),
            "username": user, "password": pw, "grant_type": "password"}
    if os.environ.get("EOG_CLIENT_SECRET"):
        data["client_secret"] = os.environ["EOG_CLIENT_SECRET"]
    r = requests.post(TOKEN_URL, data=data, headers=_UA, timeout=60)
    if not (r.ok and r.json().get("access_token")):
        raise RuntimeError(f"EOG auth failed: {r.status_code} {r.text[:200]}")
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {**_UA, "Authorization": f"Bearer {token}"}


def _list_tifgz(year: int, ver: str, token: str) -> list[str]:
    r = requests.get(BASE.format(ver=ver, year=year), headers=_auth(token), timeout=180)
    r.raise_for_status()
    return re.findall(r'href="([^"]+\.tif\.gz)"', r.text)


def _pick(files: list[str]) -> str | None:
    for key in ("median_masked", "average_masked", "median", "average"):
        hit = [f for f in files if key in f and "global" in f]
        if hit:
            return sorted(hit)[-1]
    return files[-1] if files else None


def _region_clip(gz_path, gdf_ll) -> str:
    """Clip the (gzipped) global GeoTIFF to the region window and cache a small tif."""
    minx, miny, maxx, maxy = gdf_ll.total_bounds
    pad = 0.1
    with rasterio.open(f"/vsigzip/{gz_path}") as ds:
        win = from_bounds(minx - pad, miny - pad, maxx + pad, maxy + pad, ds.transform)
        arr = ds.read(1, window=win)
        prof = ds.profile.copy()
        prof.update(height=arr.shape[0], width=arr.shape[1], transform=ds.window_transform(win),
                    driver="GTiff", compress="deflate")
    out = str(gz_path)[:-7] + "_clip.tif"
    with rasterio.open(out, "w", **prof) as dst:
        dst.write(arr, 1)
    return out


def _find_local_gz(year: int):
    """A manually-downloaded global VNL .tif.gz for this data year, dropped in data/raster/."""
    masked = [p for p in RDIR.glob("*.tif.gz") if f"_{year}_" in p.name and "masked" in p.name]
    any_ = [p for p in RDIR.glob("*.tif.gz") if f"_{year}_" in p.name]
    return (masked or any_ or [None])[0]


def fetch_indicator(region: dict, indicator: dict) -> pd.DataFrame:
    ver = indicator["viirs"].get("version", "v22")
    years = indicator["viirs"]["years"]
    gdf = load_tracts_gdf(4326)
    RDIR.mkdir(parents=True, exist_ok=True)
    have_creds = bool(os.environ.get("EOG_USERNAME") and os.environ.get("EOG_PASSWORD"))
    frames = []
    for y in years:
        clip = RDIR / f"viirs_{ver}_{y}_clip.tif"
        if not clip.exists():
            gz = _find_local_gz(y)                      # 1) manually-downloaded file
            if gz is None and have_creds:               # 2) API download (needs working EOG client)
                gz = _api_download(y, ver)
            if gz is None:
                print(f"      ! no VIIRS data for {y} — drop a *_{y}_*.tif.gz in data/raster/ "
                      f"(median-masked) or set EOG creds")
                continue
            tmp = _region_clip(gz, gdf)
            os.replace(tmp, clip)
        res = exact_extract(str(clip), gdf, ["mean"], include_cols=["geoid"], output="pandas")
        frames.append(pd.DataFrame([
            {"geoid": r.geoid, "year": y, "value": (round(r.mean, 4) if r.mean == r.mean else None), "moe": None}
            for r in res.itertuples()
        ]))
    if not frames:
        raise RuntimeError("No VIIRS years available (provide local files or EOG credentials).")
    return pd.concat(frames, ignore_index=True)


def _api_download(year: int, ver: str):
    """Best-effort EOG API download (requires a working per-account EOG OAuth client)."""
    token = get_token()
    folder = "2025" if year >= 2022 else str(year)   # v22 release folder vs v21 per-year
    base = f"https://eogdata.mines.edu/nighttime_light/annual/{ver}/{folder}/"
    files = re.findall(r'href="([^"]+\.tif\.gz)"',
                       requests.get(base, headers=_auth(token), timeout=180).text)
    cand = [f for f in files if f"_{year}_" in f] or files
    fname = _pick(cand)
    if not fname:
        return None
    gz = RDIR / fname.split("/")[-1]
    url = fname if fname.startswith("http") else base + fname
    print(f"      downloading VNL {year} ({gz.name}) ...")
    # atomic: stream to .part then rename so an interrupted download isn't cached as complete.
    tmp = gz.with_suffix(gz.suffix + ".part")
    with requests.get(url, headers=_auth(get_token()), stream=True, timeout=1800) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
    tmp.replace(gz)
    return gz

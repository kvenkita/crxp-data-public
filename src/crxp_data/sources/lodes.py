"""LEHD LODES8 WAC source: workplace jobs by 2020 census block, aggregated to region tracts.

WAC is a synthetic (privacy-noise-infused) full count of jobs at their work location; no sampling
MOE. LODES8 blocks are 2020 vintage, so aggregation to 2020 tracts needs no crosswalk.
"""
from __future__ import annotations
import gzip
import requests
import pandas as pd
from ..config import ROOT, load_source
from ..geo import load_land_area
from . import census_acs

RAW = ROOT / "warehouse" / "lodes_raw"
_ST = {"37": "nc", "45": "sc"}
# All WAC count columns we retain (total, industry, earnings, worker demographics).
WAC_COLS = (["C000"]
            + [f"CNS{i:02d}" for i in range(1, 21)]
            + [f"CE0{i}" for i in (1, 2, 3)]
            + [f"CR0{i}" for i in range(1, 8)]
            + [f"CT0{i}" for i in (1, 2)]
            + [f"CD0{i}" for i in range(1, 5)]
            + [f"CS0{i}" for i in (1, 2)])


def _aggregate_blocks(df: pd.DataFrame, region: dict) -> pd.DataFrame:
    """Sum block rows to tract (GEOID[:11]); keep only region-county blocks. Pure/testable."""
    fips = {c["fips"] for c in region["counties"]}
    gc = df["w_geocode"].astype(str).str.zfill(15)
    tract = gc.str[:11]
    keep = gc.str[:5].isin(fips)
    cols = [c for c in WAC_COLS if c in df.columns]
    out = (df.loc[keep, cols].assign(geoid=tract[keep])
             .groupby("geoid", as_index=False)[cols].sum())
    return out


def _download(st_fips: str, year: int) -> pd.DataFrame:
    """Download (once) a state-year WAC csv.gz; cache under warehouse/lodes_raw/."""
    RAW.mkdir(parents=True, exist_ok=True)
    st = _ST[st_fips]
    cache = RAW / f"{st}_wac_S000_JT00_{year}.csv.gz"
    if not cache.exists():
        url = load_source("lodes")["url_template"].format(st=st, year=year)
        r = requests.get(url, timeout=600)
        if not r.ok:
            print(f"      ! LODES {st} {year}: {r.status_code} (skipping)")
            return pd.DataFrame()
        tmp = cache.with_suffix(cache.suffix + ".part")
        tmp.write_bytes(r.content)
        tmp.replace(cache)
    with gzip.open(cache, "rt") as fh:
        return pd.read_csv(fh, dtype={"w_geocode": str})


def wac_tracts(region: dict, years: list[int]) -> pd.DataFrame:
    """WAC counts aggregated to region tracts for the given years."""
    frames = []
    for y in years:
        parts = [_download(st, y) for st in _ST]
        parts = [p for p in parts if not p.empty]
        if not parts:
            continue
        agg = _aggregate_blocks(pd.concat(parts, ignore_index=True), region)
        agg["year"] = y
        frames.append(agg)
    if not frames:
        raise RuntimeError("No LODES years available.")
    return pd.concat(frames, ignore_index=True)


INDUSTRY = {
    "office":     ["CNS09", "CNS10", "CNS11", "CNS12", "CNS13", "CNS14", "CNS20"],
    "industrial": ["CNS03", "CNS04", "CNS05", "CNS06", "CNS08"],
    "retail":     ["CNS07", "CNS17", "CNS18"],
    "health_ed":  ["CNS15", "CNS16"],
}


def _households(region: dict, years: list[int]) -> dict:
    """Households (ACS B25002_002E occupied units) per (geoid, year)."""
    raw = census_acs._fetch_api(region, ["B25002_002E"], years) \
        if census_acs.resolve_provider(region) == "api" \
        else census_acs._fetch_cr(region, ["B25002_002E"], years)
    v = "B25002_002E"
    return {(r.geoid, int(r.year)): getattr(r, v)
            for r in raw.itertuples() if getattr(r, v) == getattr(r, v)}


def _grp(row, cols):
    return sum(row.get(c, 0) or 0 for c in cols)


def fetch_indicator(region: dict, indicator: dict) -> pd.DataFrame:
    """Return long-format [geoid, year, value, moe] for the single selected LODES measure."""
    spec = indicator["lodes"]
    years = spec.get("years") or load_source("lodes")["years"]
    hh = None if spec["measure"] == "jobs_housing_balance" else {}
    long = compute_measures(wac_tracts(region, years), region, households=hh)
    sel = long[long["measure"] == spec["measure"]][["geoid", "year", "value"]].copy()
    sel["moe"] = None
    return sel.reset_index(drop=True)


def compute_measures(wac: pd.DataFrame, region: dict,
                     land_area: dict | None = None, households: dict | None = None) -> pd.DataFrame:
    """Long-format measures per (geoid, year). land_area/households injectable for tests."""
    years = sorted({int(y) for y in wac["year"].unique()})
    land = land_area if land_area is not None else load_land_area(region)
    hh = households if households is not None else _households(region, years)
    rows = []
    for r in wac.to_dict("records"):
        g, y, tot = r["geoid"], int(r["year"]), r.get("C000", 0) or 0
        a, h = land.get(g), hh.get((g, y))
        def add(measure, val):
            rows.append({"geoid": g, "year": y, "measure": measure,
                         "value": (round(val, 4) if val is not None else None)})
        add("total_jobs", tot)
        add("job_density", tot / a if a and a > 0 else None)
        add("jobs_housing_balance", tot / h if h and h > 0 else None)
        for name, cols in INDUSTRY.items():
            gj = _grp(r, cols)
            add(f"{name}_share", 100 * gj / tot if tot > 0 else None)
            add(f"{name}_density", gj / a if a and a > 0 else None)
        add("high_wage_share", 100 * (r.get("CE03", 0) or 0) / tot if tot > 0 else None)
    return pd.DataFrame(rows)

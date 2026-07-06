"""Ingest CDC PLACES model-based health estimates (Socrata, keyless), across releases.

PLACES publishes one annual release per year; each release is a fresh model fit reporting
two BRFSS data years. We stitch the six relevant releases into a time series, keeping the
newest release per (geoid, data year). Pre-flip releases (2010 census tracts) are harmonized
to 2020 tracts downstream (see harmonize.harmonize_places_rates). Each row's 95% CI half-width
is converted to a 90%-equivalent MOE so reliability is comparable with ACS.
"""
from __future__ import annotations
import requests
import pandas as pd

CI95_TO_MOE90 = 1.645 / 1.96   # convert 95% CI half-width -> 90% MOE
BASE = "https://data.cdc.gov/resource/{ds}.json"

# Verified against the live Socrata catalog 2026-06-28. Ordered oldest -> newest.
# `data_years` are the two BRFSS modeling INPUT years for each release (informational); each row
# carries a single authoritative output `year`, and the code keys off that row `year`, not `data_years`.
RELEASES = [
    {"year": 2020, "tract": "4ai3-zynv", "county": None,  # 2020 county dataset is name-keyed (no locationid/FIPS) — unusable for our join
     "vintage": 2010, "data_years": [2017, 2018]},
    {"year": 2021, "tract": "373s-ayzu", "county": "pqpp-u99h", "vintage": 2010, "data_years": [2018, 2019]},
    {"year": 2022, "tract": "nw2y-v4gm", "county": "duw2-7jbt", "vintage": 2010, "data_years": [2019, 2020]},
    {"year": 2023, "tract": "em5e-5hvn", "county": "h3ej-a9ec", "vintage": 2010, "data_years": [2020, 2021]},
    {"year": 2024, "tract": "ai6z-tcin", "county": "fu4u-a9bh", "vintage": 2020, "data_years": [2021, 2022]},
    {"year": 2025, "tract": "cwsq-ngmh", "county": "swc5-untb", "vintage": 2020, "data_years": [2022, 2023]},
]
NEWEST = RELEASES[-1]


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def newest_wins(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the max-`release` row per (geoid, year); drop `release` but preserve `vintage`
    from the winning row (downstream decides harmonization from that provenance)."""
    if df.empty:
        return df.drop(columns=["release"], errors="ignore")
    out = (df.sort_values("release")
             .drop_duplicates(["geoid", "year"], keep="last")
             .drop(columns=["release"])
             .reset_index(drop=True))
    return out


def _query(ds: str, where: str) -> list:
    rows, offset, lim = [], 0, 50000
    select = ("year,locationid,data_value,"
              "low_confidence_limit,high_confidence_limit,totalpopulation")
    while True:
        r = requests.get(BASE.format(ds=ds), params={
            "$where": where, "$select": select, "$limit": lim, "$offset": offset}, timeout=120)
        if r.status_code != 200 or not r.text.lstrip().startswith("["):
            raise RuntimeError(f"CDC PLACES {ds}: {r.status_code} {r.text[:160]}")
        batch = r.json()
        rows += batch
        if len(batch) < lim:
            break
        offset += lim
    return rows


def _records(rows: list) -> list[dict]:
    recs = []
    for d in rows:
        geoid = d.get("locationid")
        if not geoid:
            continue
        val = _f(d.get("data_value"))
        lo, hi = _f(d.get("low_confidence_limit")), _f(d.get("high_confidence_limit"))
        if lo is not None and hi is not None:
            lo, hi = min(lo, hi), max(lo, hi)
            moe = (hi - lo) / 2 * CI95_TO_MOE90
        else:
            moe = float("nan")
        # pop = total tract population; used only as a harmonization weight, not a rate
        # denominator. The adult-only totalpop18plus column is absent from pre-2024 releases.
        pop = _f(d.get("totalpopulation"))
        recs.append({"geoid": str(geoid), "year": int(d["year"]),
                     "value": val if val is not None else float("nan"),
                     "moe": moe, "pop": pop if pop is not None else float("nan")})
    return recs


def fetch_measure(region: dict, measure_id: str, dv_type: str, level: str,
                  releases=None) -> pd.DataFrame:
    """Long frame [geoid, year, value, moe, pop, vintage] across releases, newest-wins per (geoid, year).

    Each row carries the tract `vintage` (2010 or 2020) of the SOURCE release that won for that
    (geoid, year), so downstream code can decide harmonization per-row from provenance rather than
    from a measure-agnostic year-set assumption.

    level='tract' filters by countyfips and returns 11-digit tract geoids;
    level='county' filters by locationid and returns 5-digit county geoids.
    """
    releases = releases or RELEASES
    fips = "','".join(c["fips"] for c in region["counties"])
    frames = []
    for rel in releases:
        ds = rel[level]
        if not ds:
            continue          # this release has no usable dataset at this geo level
        if level == "tract":
            where = f"countyfips in ('{fips}') and measureid='{measure_id}' and data_value_type='{dv_type}'"
        else:
            where = f"locationid in ('{fips}') and measureid='{measure_id}' and data_value_type='{dv_type}'"
        recs = _records(_query(ds, where))
        for rec in recs:
            rec["release"] = rel["year"]
            rec["vintage"] = rel["vintage"]
        if recs:
            frames.append(pd.DataFrame(recs))
    if not frames:
        return pd.DataFrame(columns=["geoid", "year", "value", "moe", "pop", "vintage"])
    return newest_wins(pd.concat(frames, ignore_index=True))


def fetch_indicator(region: dict, indicator: dict) -> pd.DataFrame:
    cdc = indicator["cdc"]
    return fetch_measure(region, cdc["measure_id"],
                         cdc.get("data_value_type", "Crude prevalence"), "tract")


def fetch_indicator_county(region: dict, indicator: dict) -> pd.DataFrame:
    cdc = indicator["cdc"]
    df = fetch_measure(region, cdc["measure_id"],
                       cdc.get("data_value_type", "Crude prevalence"), "county")
    return df.drop(columns=["vintage"], errors="ignore")


def list_measures(level: str = "tract") -> pd.DataFrame:
    """Catalog of measures present in the newest release (for staging/review)."""
    ds = NEWEST[level]
    r = requests.get(BASE.format(ds=ds), params={
        "$select": "measureid,measure,category,data_value_type",
        "$group": "measureid,measure,category,data_value_type", "$limit": 500}, timeout=120)
    if r.status_code != 200 or not r.text.lstrip().startswith("["):
        raise RuntimeError(f"CDC PLACES list_measures {ds}: {r.status_code} {r.text[:160]}")
    return pd.DataFrame(r.json())

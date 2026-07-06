"""Harmonize pre-2020 ACS vintages (2010 census tracts) to 2020 census tracts.

Uses the Census 2020<->2010 tract relationship files to build an area-of-overlap
allocation factor afact(t10->t20) = AREALAND_PART / AREALAND_TRACT_10, then allocates
each raw ACS variable from 2010 tracts to 2020 tracts BEFORE indicator calc:
  - count estimates (E): area-weighted sum across contributing 2010 tracts
  - margins of error (M): sqrt(sum of (afact*moe)^2)  (independence approximation)
  - medians: area-weighted average (approximation; block-pop weighting is a future refinement)
"""
from __future__ import annotations
import io
import math
import requests
import pandas as pd
from .config import ROOT

REL_URL = "https://www2.census.gov/geo/docs/maps-data/data/rel2020/tract/tab20_tract20_tract10_st{ss}.txt"
XWALK_CSV = ROOT / "data" / "tract_2010_2020_crosswalk.csv"          # area-weighted (fallback)
POP_XWALK_CSV = ROOT / "data" / "tract_2010_2020_crosswalk_pop.csv"  # population-weighted (preferred)


def build_crosswalk(region: dict, force: bool = False) -> pd.DataFrame:
    """Return [t10, t20, afact] for the region; cache to data/ (committed; no network after).
    Prefers the population-weighted crosswalk (built by scripts/build_pop_crosswalk.py); falls
    back to the area-weighted one."""
    if POP_XWALK_CSV.exists() and not force:
        return pd.read_csv(POP_XWALK_CSV, dtype={"t10": str, "t20": str})
    if XWALK_CSV.exists() and not force:
        return pd.read_csv(XWALK_CSV, dtype={"t10": str, "t20": str})
    states = sorted({c["fips"][:2] for c in region["counties"]})
    county_fips = {c["fips"] for c in region["counties"]}
    rows = []
    for ss in states:
        txt = requests.get(REL_URL.format(ss=ss), timeout=180).text
        df = pd.read_csv(io.StringIO(txt), sep="|", dtype=str)
        df = df[df["GEOID_TRACT_10"].str[:5].isin(county_fips)]
        for _, r in df.iterrows():
            part, a10 = float(r["AREALAND_PART"]), float(r["AREALAND_TRACT_10"])
            if part <= 0 or a10 <= 0:
                continue
            rows.append({"t10": r["GEOID_TRACT_10"], "t20": r["GEOID_TRACT_20"], "afact": part / a10})
    cw = pd.DataFrame(rows)
    cw["afact"] = cw["afact"] / cw.groupby("t10")["afact"].transform("sum")  # normalize per 2010 tract
    XWALK_CSV.parent.mkdir(parents=True, exist_ok=True)
    cw.to_csv(XWALK_CSV, index=False)
    return cw


def _agg_var(vals, afact, is_moe: bool, is_median: bool):
    m = [(v, a) for v, a in zip(vals, afact) if v is not None and math.isfinite(v) and math.isfinite(a)]
    if not m:
        return float("nan")
    wsum = sum(a for _, a in m)
    if is_moe:
        val = math.sqrt(sum((v * a) ** 2 for v, a in m))
        return val / wsum if (is_median and wsum) else val
    s = sum(v * a for v, a in m)
    return (s / wsum if wsum else float("nan")) if is_median else s


def to_2020_tracts(raw: pd.DataFrame, crosswalk: pd.DataFrame, indicator: dict, vintage_years) -> pd.DataFrame:
    """Remap rows whose year is in vintage_years from 2010 tracts to 2020 tracts."""
    vset = set(vintage_years)
    if not vset or raw.empty:
        return raw
    var_cols = [c for c in raw.columns if c not in ("geoid", "year")]
    is_median = indicator["acs"].get("kind") == "median"
    parts = [raw[~raw["year"].isin(vset)].copy()]
    vin = raw[raw["year"].isin(vset)]
    if not vin.empty:
        m = vin.merge(crosswalk, left_on="geoid", right_on="t10", how="inner")
        out = []
        for (t20, year), g in m.groupby(["t20", "year"]):
            rec = {"geoid": t20, "year": int(year)}
            af = g["afact"].tolist()
            for v in var_cols:
                rec[v] = _agg_var(g[v].tolist(), af, v.endswith("M"), is_median)
            out.append(rec)
        if out:
            parts.append(pd.DataFrame(out))
    return pd.concat(parts, ignore_index=True)


def harmonize_places_rates(raw: pd.DataFrame, crosswalk: pd.DataFrame, years_2010) -> pd.DataFrame:
    """Allocate model-based prevalence RATES from 2010 to 2020 tracts via pseudo-counts.

    For each 2010-vintage year: cases = value%/100 * pop, casesM = moe/100 * pop; allocate
    cases, casesM, pop to 2020 tracts by afact; recompute value = 100*Σcases/Σpop and
    moe = 100*sqrt(Σ(afact*casesM)^2)/Σpop. Other years pass through unchanged.

    pop is the total tract population denominator used as the weighting basis.
    """
    vset = set(years_2010)
    if not vset or raw.empty:
        return raw
    keep = raw[~raw["year"].isin(vset)].copy()
    vin = raw[raw["year"].isin(vset)].copy()
    if vin.empty:
        return keep
    vin = vin[vin["value"].apply(lambda v: v is not None and math.isfinite(v))]
    vin = vin[vin["pop"].apply(lambda p: p is not None and math.isfinite(p) and p > 0)]
    if vin.empty:
        return keep
    vin["cases"] = vin["value"] / 100.0 * vin["pop"]
    vin["casesM"] = vin["moe"].fillna(0.0) / 100.0 * vin["pop"]
    m = vin.merge(crosswalk, left_on="geoid", right_on="t10", how="inner")
    m["w_cases"] = m["cases"] * m["afact"]
    m["w_pop"] = m["pop"] * m["afact"]
    m["w_casesM"] = m["casesM"] * m["afact"]
    out = []
    for (t20, year), g in m.groupby(["t20", "year"]):
        pop = g["w_pop"].sum()
        if pop <= 0:
            continue
        cases = g["w_cases"].sum()
        casesM = math.sqrt((g["w_casesM"] ** 2).sum())
        out.append({"geoid": t20, "year": int(year),
                    "value": 100.0 * cases / pop, "moe": 100.0 * casesM / pop, "pop": pop})
    parts = [keep]
    if out:
        parts.append(pd.DataFrame(out))
    return pd.concat(parts, ignore_index=True)

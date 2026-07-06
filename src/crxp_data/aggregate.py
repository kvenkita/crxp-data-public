"""Authoritative county estimates + pooled region rollup for the aggregates contract.

County values come from each SOURCE's published county-level estimate — ACS county tables,
the CDC PLACES county model, or county zonal stats (= land-area-weighted tract values) — NOT an
unweighted mean of tracts, which is biased for rates and statistically invalid for medians,
indices, and counts.

The 14-county region has no single published estimate, so it is POOLED correctly by kind:
  - counts            -> sum across counties
  - proportion / rate -> sum(numerator) / sum(denominator)         (exact pooled rate)
  - medians / indices -> population-weighted mean of county values  (documented approximation)
  - raster / zonal    -> land-area-weighted mean                    (exact regional zonal for shares)

Output: a long frame [geoid, year, value, moe, cv, reliability] with one row per region county
plus a row whose geoid is REGION_GEOID for the pooled region.
"""
from __future__ import annotations
import math
import pandas as pd

from . import geo
from .sources import census_acs
from .indicators import calc

REGION_GEOID = "REGION"


# ---------------- shared helpers ----------------
def _county_land_area(region: dict) -> dict:
    aland = geo.load_land_area(region)  # {tract_geoid: sq mi}
    out: dict[str, float] = {}
    for g, a in aland.items():
        out[g[:5]] = out.get(g[:5], 0.0) + (a or 0.0)
    return out


def _apply_density(tidy, area_map: dict):
    """Convert a count to per-square-mile density (value & moe scale by 1/area; CV/reliability unchanged)."""
    rows = []
    for r in tidy.itertuples():
        a = area_map.get(r.geoid)
        v = (round(r.value / a, 4) if (r.value is not None and a and a > 0) else None)
        m = (round(r.moe / a, 4) if (getattr(r, "moe", None) is not None and a and a > 0) else None)
        rows.append({"geoid": r.geoid, "year": int(r.year), "value": v, "moe": m,
                     "cv": getattr(r, "cv", None), "reliability": getattr(r, "reliability", None)})
    return pd.DataFrame(rows)


def _sum_raw(raw, var_ids: list[str]):
    """Region raw row per year: estimate vars summed, MOE vars combined in quadrature (independence)."""
    rows = []
    for y, g in raw.groupby("year"):
        rec = {"geoid": REGION_GEOID, "year": int(y)}
        for v in var_ids:
            col = [x for x in g[v].tolist() if x is not None and math.isfinite(x)]
            if v.endswith("M"):
                rec[v] = math.sqrt(sum(x * x for x in col)) if col else float("nan")
            else:
                rec[v] = sum(col) if col else float("nan")
        rows.append(rec)
    return pd.DataFrame(rows)


def _popweighted_region(county_tidy, pop: dict, region: dict):
    """Region = population-weighted mean of county values (for medians/indices/model-based)."""
    counties = sorted(county_tidy["geoid"].unique())
    vm = {(r.geoid, int(r.year)): (r.value, getattr(r, "moe", None)) for r in county_tidy.itertuples()}
    rows = []
    for y in sorted({int(yy) for yy in county_tidy["year"].unique()}):
        num = wsum = mvar = 0.0
        for c in counties:
            v = vm.get((c, y))
            w = pop.get((c, y))
            if not v or v[0] is None or w is None or not math.isfinite(w) or w <= 0:
                continue
            num += v[0] * w
            wsum += w
            if v[1] is not None and math.isfinite(v[1]):
                mvar += (w * v[1]) ** 2
        if wsum <= 0:
            continue
        rows.append({"geoid": REGION_GEOID, "year": y,
                     "value": num / wsum, "moe": (math.sqrt(mvar) / wsum if mvar > 0 else float("nan"))})
    return calc.add_reliability(pd.DataFrame(rows), region) if rows else pd.DataFrame(
        columns=["geoid", "year", "value", "moe", "cv", "reliability"])


# ---------------- per-source builders ----------------
def _acs(ind: dict, region: dict, years: list[int]):
    acs = ind["acs"]
    kind = acs.get("kind", "median")
    per_land = acs.get("per_land_area")
    raw = census_acs.fetch_indicator_county(region, ind, years)          # geoid = 5-digit county FIPS
    county = calc.compute_indicator(raw, ind, region)
    carea = _county_land_area(region) if per_land else None
    if per_land:
        county = _apply_density(county, carea)

    if kind in ("proportion", "rate", "count", "number"):
        region_tidy = calc.compute_indicator(_sum_raw(raw, census_acs.acs_var_ids(ind)), ind, region)
        if per_land:
            region_tidy = _apply_density(region_tidy, {REGION_GEOID: sum(carea.values())})
    else:  # median / index / average -> population-weighted mean of county values
        region_tidy = _popweighted_region(county, census_acs.county_population(region, years), region)
    return pd.concat([county, region_tidy], ignore_index=True)


def _cdc(ind: dict, region: dict):
    from .sources import cdc_places
    raw = cdc_places.fetch_indicator_county(region, ind)                 # geoid = 5-digit county FIPS
    county = calc.add_reliability(raw, region)
    years = sorted({int(y) for y in county["year"].unique()})
    region_tidy = _popweighted_region(county, census_acs.county_population(region, years), region)
    return pd.concat([county, region_tidy], ignore_index=True)


def _zonal(ind: dict, region: dict, tract_tidy):
    """Raster/VIIRS: county & region = land-area-weighted mean of tract values (= the zonal value)."""
    aland = geo.load_land_area(region)
    counties = sorted({c["fips"] for c in region["counties"]})
    geoids = sorted(tract_tidy["geoid"].unique())
    vt = {(r.geoid, int(r.year)): r.value for r in tract_tidy.itertuples()}
    years = sorted({int(y) for y in tract_tidy["year"].unique()})

    def wmean(gids, y):
        num = den = 0.0
        for g in gids:
            v = vt.get((g, y))
            a = aland.get(g)
            if v is None or a is None or a <= 0:
                continue
            num += v * a
            den += a
        return round(num / den, 4) if den > 0 else None

    rows = []
    for y in years:
        for c in counties:
            rows.append({"geoid": c, "year": y, "value": wmean([g for g in geoids if g[:5] == c], y), "moe": None})
        rows.append({"geoid": REGION_GEOID, "year": y, "value": wmean(geoids, y), "moe": None})
    return calc.add_reliability(pd.DataFrame(rows), region)  # moe None -> cv/reliability null


def build_county_region(ind: dict, region: dict, tract_tidy, present_years: list[int]):
    source = ind.get("source", "acs")
    if source == "acs":
        return _acs(ind, region, present_years)
    if source == "cdc_places":
        return _cdc(ind, region)
    if source in ("raster", "viirs"):
        return _zonal(ind, region, tract_tidy)
    raise ValueError(f"county/region rollup: unknown source {source!r}")

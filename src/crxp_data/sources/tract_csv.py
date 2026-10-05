"""Generic tract-level CSV source ("bring your own data").

Reads any CSV keyed by census-tract GEOID and emits the standard tidy frame
[geoid, year, value, moe] that every other source produces, so the file flows through the same
QA gate, warehouse, analytics, and contract export. A 90% MOE column is optional. 2010-vintage
tracts are allocated to 2020 tracts with the committed crosswalk: counts by allocation factor,
rates and proportions by population-weighted pseudo-counts (which need a pop_col). Medians and
indices on 2010 tracts are rejected: there is no defensible allocation for them.
"""
from __future__ import annotations
import pandas as pd

from ..config import ROOT
from .. import harmonize

KINDS = ("count", "proportion", "rate", "median", "index")
REQUIRED = ("path", "geoid_col", "value_col", "kind", "source_label")
VINTAGE_TOLERANCE = 0.05   # share of in-region GEOIDs allowed to be absent from the declared vintage


class TractCsvConfigError(ValueError):
    pass


def spec(ind: dict) -> tuple[dict, int]:
    slug = ind.get("slug", "?")
    tc = ind.get("tract_csv")
    if not tc:
        raise TractCsvConfigError(f"{slug}: source tract_csv needs a tract_csv: block")
    for k in REQUIRED:
        if not tc.get(k):
            raise TractCsvConfigError(f"{slug}: tract_csv.{k} is required")
    kind = tc["kind"]
    if kind not in KINDS:
        raise TractCsvConfigError(f"{slug}: tract_csv.kind {kind!r} is not one of {list(KINDS)}")
    if ("year" in tc) == ("year_col" in tc):
        raise TractCsvConfigError(f"{slug}: set exactly one of tract_csv.year or tract_csv.year_col")
    vintage = int(tc.get("tract_vintage", 2020))
    if vintage not in (2010, 2020):
        raise TractCsvConfigError(f"{slug}: tract_csv.tract_vintage must be 2010 or 2020, got {vintage}")
    if vintage == 2010 and kind in ("median", "index"):
        raise TractCsvConfigError(
            f"{slug}: kind {kind!r} on 2010 tracts cannot be allocated to 2020 tracts; "
            f"supply 2020-tract data")
    if vintage == 2010 and kind in ("proportion", "rate") and not tc.get("pop_col"):
        raise TractCsvConfigError(
            f"{slug}: a 2010-tract {kind} needs tract_csv.pop_col (2010-tract population) to allocate")
    return tc, vintage


def read_csv(tc: dict) -> pd.DataFrame:
    path = str(tc["path"])
    src = path if path.startswith(("http://", "https://")) else ROOT / path
    return pd.read_csv(src, dtype={tc["geoid_col"]: str}, low_memory=False)


def normalize(df: pd.DataFrame, ind: dict, region_counties: set[str]) -> pd.DataFrame:
    tc, _ = spec(ind)
    slug = ind.get("slug", "?")
    gcol, vcol = tc["geoid_col"], tc["value_col"]
    mcol, ycol, pcol = tc.get("moe_col"), tc.get("year_col"), tc.get("pop_col")
    need = [gcol, vcol] + [c for c in (mcol, ycol, pcol) if c]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise TractCsvConfigError(
            f"{slug}: column(s) {missing} not in the CSV (first columns: {list(df.columns)[:12]})")
    geoid = (df[gcol].astype(str).str.strip()
             .str.replace(r"\.0$", "", regex=True).str.zfill(11))
    out = pd.DataFrame({"geoid": geoid})
    out["year"] = pd.to_numeric(df[ycol]).astype(int) if ycol else int(tc["year"])
    out["value"] = pd.to_numeric(df[vcol], errors="coerce")
    out["moe"] = pd.to_numeric(df[mcol], errors="coerce") if mcol else float("nan")
    if pcol:
        out["pop"] = pd.to_numeric(df[pcol], errors="coerce")
    out = out[out["geoid"].str[:5].isin(region_counties)].reset_index(drop=True)
    if out.empty:
        raise TractCsvConfigError(
            f"{slug}: no rows matched the region's counties (does {gcol!r} hold 11-digit tract GEOIDs?)")
    dup = out.duplicated(["geoid", "year"]).sum()
    if dup:
        raise TractCsvConfigError(f"{slug}: {dup} duplicate (geoid, year) rows in the CSV")
    return out


def allocate_2010(df: pd.DataFrame, crosswalk: pd.DataFrame, kind: str) -> pd.DataFrame:
    """Allocate 2010-tract rows to 2020 tracts (kind already validated by spec())."""
    cols = ["geoid", "year", "value", "moe"]
    had_moe = df["moe"].notna().any()
    if kind == "count":
        m = df.merge(crosswalk, left_on="geoid", right_on="t10", how="inner")
        rows = []
        for (t20, y), g in m.groupby(["t20", "year"]):
            af = g["afact"].tolist()
            rows.append({"geoid": t20, "year": int(y),
                         "value": harmonize._agg_var(g["value"].tolist(), af, False, False),
                         "moe": harmonize._agg_var(g["moe"].tolist(), af, True, False)})
        return pd.DataFrame(rows, columns=cols)
    years = {int(y) for y in df["year"].unique()}
    out = harmonize.harmonize_places_rates(df, crosswalk, years)[cols].copy()
    if not had_moe:  # harmonize_places_rates fills a missing MOE with 0; keep "not available"
        out["moe"] = float("nan")
    return out


def check_vintage(df: pd.DataFrame, vintage: int, crosswalk: pd.DataFrame, slug: str) -> None:
    """Stop when the file's GEOIDs don't match the declared tract vintage.

    2010 and 2020 tracts share many IDs, so a file on the wrong vintage still matches most of the
    region and would pass the QA coverage floor with a third of the map blank.
    """
    sets = {2010: set(crosswalk["t10"]), 2020: set(crosswalk["t20"])}
    ids = set(df["geoid"])
    miss = ids - sets[vintage]
    share = len(miss) / len(ids) if ids else 0.0
    if share <= VINTAGE_TOLERANCE:
        return
    other = 2020 if vintage == 2010 else 2010
    in_other = len(miss & sets[other]) / len(miss)
    hint = (f"; {in_other:.0%} of those are {other} tracts, so set tract_vintage: {other}"
            if in_other > 0.5 else "")
    raise TractCsvConfigError(
        f"{slug}: {share:.0%} of the file's in-region GEOIDs ({len(miss)}/{len(ids)}) are not "
        f"{vintage} tracts{hint}")


def fetch_indicator(region: dict, ind: dict, crosswalk: pd.DataFrame | None = None) -> pd.DataFrame:
    tc, vintage = spec(ind)
    counties = {c["fips"] for c in region["counties"]}
    df = normalize(read_csv(tc), ind, counties)
    cw = crosswalk if crosswalk is not None else harmonize.build_crosswalk(region)
    check_vintage(df, vintage, cw, ind.get("slug", "?"))
    if vintage == 2010:
        df = allocate_2010(df, cw, tc["kind"])
    return df[["geoid", "year", "value", "moe"]].reset_index(drop=True)

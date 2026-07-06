"""Stage ALL CDC PLACES measures (tract + county) into the raw warehouse for later review.

Pulls every measure in the newest release across all releases (newest-release-wins),
harmonizes the 2010-vintage tract ROWS to 2020 tracts (provenance-driven), computes
value+MOE+CV+reliability, and writes one parquet per measure per geography plus a
catalog.csv decision aid.

This does NOT touch indicator configs, the app manifest, or run a handoff — pure staging.
Run from crxp-data:  PYTHONPATH=src .venv/Scripts/python.exe scripts/stage_cdc_all.py
"""
from __future__ import annotations
import pandas as pd
from crxp_data import config, harmonize
from crxp_data.indicators import calc
from crxp_data.sources import cdc_places

OUT = config.ROOT / "warehouse" / "cdc_raw"
DV_TYPE = "Crude prevalence"


def _rel_counts(df: pd.DataFrame, year: int) -> dict:
    sub = df[df["year"] == year]
    c = sub["reliability"].value_counts(dropna=False).to_dict()
    return {str(k): int(v) for k, v in c.items()}


def _harmonize_tract(raw: pd.DataFrame, cw: pd.DataFrame) -> pd.DataFrame:
    """Harmonize only the vintage-2010 rows to 2020 tracts; 2020-native rows pass through."""
    if raw.empty or not (raw["vintage"] == 2010).any():
        return raw.drop(columns=["vintage"], errors="ignore")
    r10 = raw[raw["vintage"] == 2010].drop(columns=["vintage"])
    r20 = raw[raw["vintage"] != 2010].drop(columns=["vintage"])
    y2010 = sorted({int(y) for y in r10["year"].unique()})
    r10 = harmonize.harmonize_places_rates(r10, cw, set(y2010))
    # native rows (r20) first + keep="first" => newer 2020-tract estimate wins on any (geoid,year) tie
    return pd.concat([r20, r10], ignore_index=True).drop_duplicates(
        ["geoid", "year"], keep="first")


def main():
    region = config.load_region()
    cw = harmonize.build_crosswalk(region)
    meas = cdc_places.list_measures("tract")
    (OUT / "tract").mkdir(parents=True, exist_ok=True)
    (OUT / "county").mkdir(parents=True, exist_ok=True)
    catalog = []
    for _, m in meas.iterrows():
        mid = m["measureid"]
        for level in ("tract", "county"):
            raw = cdc_places.fetch_measure(region, mid, DV_TYPE, level)
            if raw.empty:
                continue
            if level == "tract":
                raw = _harmonize_tract(raw, cw)
            else:
                raw = raw.drop(columns=["vintage"], errors="ignore")  # county: not harmonized
            tidy = calc.add_reliability(raw, region)
            tidy.to_parquet(OUT / level / f"{mid}.parquet", index=False)
            years = sorted({int(y) for y in tidy["year"].unique()})
            catalog.append({
                "measureid": mid, "measure": m.get("measure", ""),
                "category": m.get("category", ""), "level": level,
                "years": ",".join(str(y) for y in years),
                "latest_year": years[-1] if years else None,
                "reliability_latest": str(_rel_counts(tidy, years[-1]) if years else {}),
            })
            print(f"  staged {mid:14} {level:6} years={years}")
    cat = pd.DataFrame(catalog).sort_values(["measureid", "level"])
    cat.to_csv(OUT / "catalog.csv", index=False, encoding="utf-8")
    print(f"\nWrote {len(cat)} measure x level rows -> {(OUT / 'catalog.csv')}")


if __name__ == "__main__":
    main()

"""Stage ALL LODES measures (core + industry mix + high-wage + worker demographics) to the
warehouse as future inventory. Does NOT touch indicator configs, the manifest, or run a handoff.
Run from crxp-data:  PYTHONPATH=src .venv/Scripts/python.exe scripts/stage_lodes_all.py
"""
from __future__ import annotations
from crxp_data import config, geo
from crxp_data.sources import lodes

OUT = config.ROOT / "warehouse" / "lodes_inventory"


def main():
    region = config.load_region()
    years = config.load_source("lodes")["years"]
    long = lodes.compute_measures(lodes.wac_tracts(region, years), region)
    allowed = set(geo.load_tract_centroids())
    long = long[long["geoid"].isin(allowed)]
    OUT.mkdir(parents=True, exist_ok=True)
    for measure, g in long.groupby("measure"):
        path = OUT / f"{measure}.parquet"
        g.to_parquet(path, index=False)
        print(f"      {measure}: {len(g)} rows -> {path.relative_to(config.ROOT)}")
    print(f"Done. {long['measure'].nunique()} measures staged, "
          f"years {sorted({int(y) for y in long['year'].unique()})}.")


if __name__ == "__main__":
    main()

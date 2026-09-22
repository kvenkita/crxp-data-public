"""End-to-end build for one indicator: ingest -> calc(MOE) -> spatial -> warehouse -> app export.

Usage:  python -m crxp_data.build household-income [--handoff] [--reexport]
  --handoff   also copies/merges the app data contract into crxp/static/data.
  --reexport  rebuild the app contract from the existing warehouse (no fetch/recompute) —
              useful after changing export logic or comparable-period definitions.
"""
from __future__ import annotations
import sys
import shutil
import datetime as dt
import pandas as pd

from . import config, geo, export_crxp, harmonize, provenance, aggregate
from .sources import census_acs
from .indicators import calc
from .indicators.calc import significant_diff
from .warehouse import write_warehouse, read_warehouse, read_county_warehouse, write_county_warehouse


def run(slug: str, handoff: bool = False, reexport: bool = False, refetch: bool = False,
        reharmonize: bool = False):
    region = config.load_region()
    ind = config.load_indicator(slug)
    annual = region["acs"]["annual_years"]
    max_y = max(annual)
    # Non-overlapping comparable endpoints, derived dynamically from the latest year:
    # latest, latest-5, latest-10 (e.g. 2024 -> 2014/2019/2024; add 2025 -> 2015/2020/2025).
    comparable = sorted({max_y - 10, max_y - 5, max_y})
    all_years = sorted(set(annual) | set(comparable))
    source = ind.get("source", "acs")
    centroids = geo.load_tract_centroids()
    allowed = set(centroids)
    acs_existing = None  # set in the ACS branch for incremental merge

    if reexport:
        print("[1/4] Re-export from warehouse (no fetch) ...")
        tidy = read_warehouse(ind["id"])
        if tidy is None or tidy.empty:
            raise SystemExit(f"no warehouse rows for indicator {ind['id']}; run a full build first")
        tidy = tidy[tidy["geoid"].isin(allowed)].copy()
        print(f"      loaded {len(tidy)} rows, years {sorted({int(y) for y in tidy['year'].unique()})}")
    elif source == "acs":
        # Incremental by default: fetch only years not already in the warehouse, then merge.
        acs_existing = None if refetch else read_warehouse(ind["id"])
        if reharmonize and acs_existing is not None:
            # drop the 2010-vintage years so they are re-fetched and re-harmonized (new crosswalk)
            v2010set = set(region["acs"].get("tract2010_years", []))
            acs_existing = acs_existing[~acs_existing["year"].isin(v2010set)].copy()
        have = {int(y) for y in acs_existing["year"].unique()} if acs_existing is not None else set()
        need = [y for y in all_years if y not in have]
        print(f"[1/4] Ingesting ACS {ind['acs']['table']}: fetch {need or 'nothing new'} "
              f"(have {sorted(have) or 'none'}) ...")
        if need:
            raw = census_acs.fetch_indicator(region, ind, need)
            v2010 = [y for y in region["acs"].get("tract2010_years", []) if y in need]
            if v2010:
                cw = harmonize.build_crosswalk(region)
                xwalk_kind = "population-weighted" if harmonize.POP_XWALK_CSV.exists() else "area-weighted"
                raw = harmonize.to_2020_tracts(raw, cw, ind, v2010)
                print(f"      harmonized {v2010} from 2010->2020 tracts ({xwalk_kind} crosswalk)")
            tidy = calc.compute_indicator(raw, ind, region)
        else:
            tidy = (acs_existing.iloc[0:0].copy() if acs_existing is not None
                    else read_warehouse(ind["id"]))
        src_meta = {"est_method": "acs_direct", "source_id": "acs", "span": 4, "rolling": True}
    elif source == "cdc_places":
        from .sources import cdc_places
        print(f"[1/6] Ingesting CDC PLACES {ind['cdc']['measure_id']} (tract, all releases) ...")
        raw = cdc_places.fetch_indicator(region, ind)   # newest-release-wins, cols incl. pop, vintage
        # Harmonize per-ROW by source-release vintage (provenance), not by year: a row is 2010-tract
        # iff its data came from a 2010-vintage release. Only vintage-2010 rows reach the crosswalk;
        # 2020-native rows pass through untouched (robust even if a year ever carried both vintages).
        # (A registry year-set assumption is wrong: e.g. the 2023 release is 2010-tract and reports
        # data year 2021 for most measures.)
        print("[2/6] Calc (value + MOE + CV + reliability) ...")
        if not raw.empty and (raw["vintage"] == 2010).any():
            cw = harmonize.build_crosswalk(region)
            xwalk_kind = "population-weighted" if harmonize.POP_XWALK_CSV.exists() else "area-weighted"
            r10 = raw[raw["vintage"] == 2010].drop(columns=["vintage"])
            r20 = raw[raw["vintage"] != 2010].drop(columns=["vintage"])
            y2010 = sorted({int(y) for y in r10["year"].unique()})
            r10 = harmonize.harmonize_places_rates(r10, cw, set(y2010))
            # native (r20) is concatenated first so keep="first" makes the newer 2020-tract
            # estimate win over any harmonized 2010-vintage row sharing a (geoid, year).
            raw_clean = pd.concat([r20, r10], ignore_index=True).drop_duplicates(
                ["geoid", "year"], keep="first")
            print(f"      harmonized {y2010} from 2010->2020 tracts ({xwalk_kind} crosswalk)")
        else:
            raw_clean = raw.drop(columns=["vintage"], errors="ignore")
        tidy = calc.add_reliability(raw_clean, region)  # reads value/moe; ignores the extra pop col
        print(f"      years {sorted({int(y) for y in tidy['year'].unique()})}")
        src_meta = {"est_method": "cdc_places_mrp", "source_id": "cdc_places", "span": 0, "rolling": False}
    elif source == "raster":
        from .sources import raster_nlcd
        _rsrc = ind["raster"].get("coverage_template") or ind["raster"].get("outer_zip") or ind["raster"].get("product")
        print(f"[1/6] Ingesting raster {_rsrc} (zonal stats to tracts) ...")
        raw = raster_nlcd.fetch_indicator(region, ind)
        print("[2/6] Calc (zonal value; no sampling MOE) ...")
        tidy = calc.add_reliability(raw, region)  # moe=None -> cv/reliability null
        src_meta = {"est_method": "raster_zonal", "source_id": ind["raster"].get("source_id", "nlcd"), "span": 0, "rolling": False}
    elif source == "viirs":
        from .sources import viirs
        print("[1/6] Ingesting VIIRS nighttime lights (EOG VNL, zonal mean to tracts) ...")
        raw = viirs.fetch_indicator(region, ind)
        print("[2/6] Calc (zonal mean radiance; no sampling MOE) ...")
        tidy = calc.add_reliability(raw, region)
        src_meta = {"est_method": "viirs_zonal", "source_id": "viirs", "span": 0, "rolling": False}
    elif source == "lodes":
        from .sources import lodes
        print("[1/6] Ingesting LODES WAC (workplace jobs, block->tract) ...")
        raw = lodes.fetch_indicator(region, ind)
        print("[2/6] Calc (job measure; no sampling MOE) ...")
        tidy = calc.add_reliability(raw, region)
        src_meta = {"est_method": "lodes_wac", "source_id": "lodes", "span": 0, "rolling": False}
    else:
        raise SystemExit(f"unknown source {source!r}")

    if not reexport:
        # keep to the app's 2020 tract set (pre-2020 years already harmonized above)
        before = tidy["geoid"].nunique()
        tidy = tidy[tidy["geoid"].isin(allowed)].copy()
        print(f"      kept {tidy['geoid'].nunique()}/{before} geoids in the 2020 tract set")

        if source == "acs" and ind["acs"].get("per_land_area"):
            amap = geo.load_land_area(region)
            a = tidy["geoid"].map(amap)
            tidy["value"] = [round(v / x, 4) if (x and x > 0 and v is not None) else None for v, x in zip(tidy["value"], a)]
            tidy["moe"] = [round(m / x, 4) if (x and x > 0 and m is not None) else None for m, x in zip(tidy["moe"], a)]
            print("      converted to per-square-mile density (CV/reliability unchanged)")

        if source == "acs" and acs_existing is not None:
            cols = ["geoid", "year", "value", "moe", "cv", "reliability"]
            tidy = (pd.concat([acs_existing[cols], tidy[cols]], ignore_index=True)
                    .drop_duplicates(["geoid", "year"], keep="last"))
            print(f"      merged with warehouse -> years {sorted({int(y) for y in tidy['year'].unique()})}")

        from .qa import check_tidy
        qa_years = sorted({int(y) for y in tidy["year"].unique()})
        rep = check_tidy(tidy, expected_geoids=allowed, years=qa_years,
                         value_range=ind.get("qa", {}).get("range"), label=ind["slug"])
        print(f"      QA gate OK ({len(rep)} years checked; coverage/null-rate/range within bounds)")

        print("[2/4] Warehouse (parquet + duckdb) ...")
        wh = tidy.copy()
        wh["indicator_id"] = ind["id"]
        wh["period_end"] = wh["year"]
        wh["period_start"] = wh["year"] - src_meta["span"]
        wh["is_rolling"] = src_meta["rolling"]
        wh["est_method"] = src_meta["est_method"]
        wh["source_id"] = src_meta["source_id"]
        wh["source_vintage"] = wh["year"].astype(str)
        wh["redacted"] = False
        wh["created"] = dt.date.today().isoformat()
        pq, n = write_warehouse(wh, ind["id"])
        print(f"      wrote {n} rows -> {pq.relative_to(config.ROOT)}")

    print("[3/4] Comparable-period change (non-overlapping pairs) ...")
    present_set = {int(y) for y in tidy["year"].unique()}
    v = {(r.geoid, int(r.year)): (r.value, r.moe) for r in tidy.itertuples()}
    for y1, y2 in [(max_y - 5, max_y), (max_y - 10, max_y)]:
        if y1 not in present_set or y2 not in present_set:
            continue
        sig = tot = 0
        for g in tidy["geoid"].unique():
            a, b = v.get((g, y1)), v.get((g, y2))
            if not a or not b or a[0] is None or b[0] is None:
                continue
            res = significant_diff(a[0], a[1], b[0], b[1])
            if res is None:
                continue
            tot += 1
            sig += 1 if res else 0
        print(f"      {y1}->{y2}: {sig}/{tot} tracts changed significantly (90%)")

    print("[4/4] App contract (values + analytics + aggregates) ...")
    # export every year present (incl. the non-overlapping anchors, e.g. 2014) so the app can
    # compute both comparable-period changes; the app derives the periods from the latest year.
    present = sorted(present_set)
    ann = tidy[tidy["year"].isin(present)]
    vf = export_crxp.build_value_file(ind, ann, present)
    zdoc, ldoc = export_crxp.build_analytics(ind, ann, present, centroids)
    # Authoritative county + pooled region rollup (not an unweighted mean of tracts).
    # On --reexport reuse a cached rollup if present; otherwise compute (county ACS/CDC are fetched
    # fresh, but tracts/rasters are reused from the warehouse) and persist it.
    county_df = read_county_warehouse(ind["id"]) if reexport else None
    if county_df is None or county_df.empty:
        county_df = aggregate.build_county_region(ind, region, ann, present)
        cpq, cn = write_county_warehouse(county_df, ind["id"])
        print(f"      county+region rollup -> {cn} rows ({cpq.relative_to(config.ROOT)})")
    agg = export_crxp.build_aggregates(ind, county_df, present)
    export_crxp.write_contract(ind, vf, zdoc, ldoc)
    print(f"      wrote exports/crxp/data/.../{ind['id']}.json (years {present})")

    print("Handoff ...")
    if handoff:
        dest = config.ROOT.parent / "crxp" / "static" / "data"
        export_crxp.merge_into_app(ind, vf, zdoc, ldoc, agg, dest)
        provenance.write(dest, build_date=dt.date.today().isoformat())
        print(f"      merged into {dest.relative_to(config.ROOT.parent)} (values, analytics, meta, manifest, aggregates, provenance)")
    else:
        print("      (skipped; pass --handoff to merge into crxp/static/data)")
    print("Done.")


if __name__ == "__main__":
    args = sys.argv[1:]
    handoff = "--handoff" in args
    reexport = "--reexport" in args  # rebuild app contract from the warehouse (no re-fetch)
    refetch = "--refetch" in args    # ACS: force a full re-fetch instead of incremental
    reharmonize = "--reharmonize" in args  # ACS: re-fetch+re-harmonize only the 2010-vintage years
    slugs = [a for a in args if not a.startswith("--")] or ["household-income"]
    for s in slugs:
        run(s, handoff=handoff, reexport=reexport, refetch=refetch, reharmonize=reharmonize)

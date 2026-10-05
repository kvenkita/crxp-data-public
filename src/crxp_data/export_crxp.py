"""Emit the CRXP app data contract (values + analytics) from pipeline output.

Matches crxp/static/data shapes and ADDS moe/cv/reliability arrays (consumed by the
app's forthcoming uncertainty UI; ignored by the current app)."""
from __future__ import annotations
import json
import os
import math
from pathlib import Path
from .config import ROOT
from . import spatial

EXPORT = ROOT / "exports" / "crxp" / "data"
SCHEMA_VERSION = 1  # bump when the data-contract shape changes; the app asserts a supported version


def _atomic_write_text(path: Path, text: str):
    """Write via a temp file + atomic replace so a crash mid-write never leaves a truncated file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _clean(v):
    """NaN/inf -> None so the JSON is valid (JSON has no NaN literal)."""
    if v is None:
        return None
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def _by_geoid_year(df, col, geoids, years):
    look = {(r.geoid, int(r.year)): getattr(r, col) for r in df.itertuples()}
    return {g: [_clean(look.get((g, y))) for y in years] for g in geoids}


def build_value_file(indicator: dict, df, annual_years: list[int], classes: int = 5) -> dict:
    geoids = sorted(df["geoid"].unique())
    years = sorted(annual_years)
    values = _by_geoid_year(df, "value", geoids, years)
    moe = _by_geoid_year(df, "moe", geoids, years)
    cv = _by_geoid_year(df, "cv", geoids, years)
    reliability = _by_geoid_year(df, "reliability", geoids, years)

    pooled = [v for g in geoids for v in values[g] if v is not None]
    dom = spatial.summarize(pooled, classes)
    stats = {}
    for yi, y in enumerate(years):
        col = [values[g][yi] for g in geoids]
        stats[str(y)] = spatial.summarize(col, classes)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "indicatorId": indicator["id"],
        "geoLevel": "tract",
        "years": years,
        "values": values,
        "moe": moe,
        "cv": cv,
        "reliability": reliability,
        "breaks": [round(b, 4) for b in dom["breaks"]],
        "domain": {k: round(dom[k], 4) for k in ("min", "max", "p1", "p99")},
        "stats": {y: {**{k: round(s[k], 4) for k in ("min", "max", "p1", "p99")},
                      "breaks": [round(b, 4) for b in s["breaks"]]} for y, s in stats.items()},
    }


def build_analytics(indicator: dict, df, annual_years: list[int], centroids: dict):
    """Compute z + LISA per year from the annual values; return (z_doc, lisa_doc)."""
    geoids = sorted(df["geoid"].unique())
    years = sorted(annual_years)
    values = _by_geoid_year(df, "value", geoids, years)
    pts = [(g, centroids[g][0], centroids[g][1]) for g in geoids if g in centroids]
    weights = spatial.knn_weights(pts, k=8)
    z_out = {g: [] for g in geoids}
    lisa_out = {g: [] for g in geoids}
    for yi, y in enumerate(years):
        col = [values[g][yi] for g in geoids]
        zs = spatial.zscores(col)
        for g, zv in zip(geoids, zs):
            z_out[g].append(None if zv is None else round(zv, 3))
        obs = [(g, values[g][yi]) for g in geoids]
        res = spatial.local_moran(obs, weights)
        for g in geoids:
            lisa_out[g].append(res[g]["quadrant"])
    z_doc = {"indicatorId": indicator["id"], "years": years, "z": z_out}
    lisa_doc = {"indicatorId": indicator["id"], "years": years, "quadrants": lisa_out}
    return z_doc, lisa_doc


def build_aggregates(indicator: dict, county_df, years: list[int], classes: int = 5) -> dict:
    """County + region aggregates (+ pooled breaks/domain) for aggregates.json[id].

    Consumes the AUTHORITATIVE county/region frame from `aggregate.build_county_region`:
    county values are each source's published county estimate (not a tract average), and the
    REGION row is correctly pooled (sum / pooled-rate / population-weighted) by indicator kind.
    Margins of error are carried straight through. Indicators without sampling MOE (raster/VIIRS)
    omit the MOE keys.
    """
    from .aggregate import REGION_GEOID
    years = sorted(years)
    counties = sorted(g for g in county_df["geoid"].unique() if g != REGION_GEOID)
    vmap = {(r.geoid, int(r.year)): r.value for r in county_df.itertuples()}
    has_moe = "moe" in county_df.columns
    mmap = {(r.geoid, int(r.year)): r.moe for r in county_df.itertuples()} if has_moe else {}

    def _r(x):
        return round(x, 4) if (x is not None and isinstance(x, (int, float)) and math.isfinite(x)) else None

    def series(g, src):
        return [_r(src.get((g, y))) for y in years]

    region_avg = series(REGION_GEOID, vmap)
    county_avg = {c: series(c, vmap) for c in counties}
    pooled = [v for c in counties for v in county_avg[c] if v is not None]
    dom = spatial.summarize(pooled, classes)
    out = {
        "years": years, "regionAvg": region_avg, "countyAvg": county_avg,
        "breaks": [round(b, 4) for b in dom["breaks"]],
        "domain": {"min": round(dom["min"], 4), "max": round(dom["max"], 4)},
    }
    if has_moe:
        region_moe = series(REGION_GEOID, mmap)
        if any(m is not None for m in region_moe) or any(mmap.get((c, y)) is not None for c in counties for y in years):
            out["regionMoe"] = region_moe
            out["countyMoe"] = {c: series(c, mmap) for c in counties}
    return out


SOURCE_LABELS = {
    "acs": "U.S. Census Bureau, American Community Survey 5-Year Estimates",
    "cdc_places": "CDC PLACES (model-based small-area estimates)",
    "raster": "U.S. Geological Survey, National Land Cover Database (NLCD)",
    "viirs": "Earth Observation Group, VIIRS Nighttime Lights (VNL V2)",
    "lodes": "U.S. Census Bureau, LEHD Origin-Destination Employment Statistics (LODES)",
}


SOURCE_LINKS = {"cdc_places": "https://www.cdc.gov/places/", "raster": "https://www.mrlc.gov/",
                "viirs": "https://eogdata.mines.edu/products/vnl/",
                "lodes": "https://lehd.ces.census.gov/data/"}


def _source_label(indicator: dict) -> str:
    if indicator.get("source") == "tract_csv":
        return indicator["tract_csv"]["source_label"]
    return SOURCE_LABELS.get(indicator.get("source", "acs"), SOURCE_LABELS["acs"])


def _source_link(indicator: dict) -> str | None:
    if indicator.get("source") == "tract_csv":
        return indicator["tract_csv"].get("source_url")
    return SOURCE_LINKS.get(indicator.get("source", "acs"), "https://www.census.gov/programs-surveys/acs")


def _about_text(indicator: dict, span: str) -> str:
    if indicator.get("source") == "tract_csv":
        tc = indicator["tract_csv"]
        harm = (" The source reports 2010 census tracts; values were allocated to 2020 tracts with the "
                "platform's tract crosswalk." if int(tc.get("tract_vintage", 2020)) == 2010 else "")
        moe = ("Values carry the source's published margins of error, and low-reliability estimates "
               "are flagged." if tc.get("moe_col") else
               "The source publishes no margin of error, so no reliability flag is shown.")
        how = "summed" if tc["kind"] == "count" else "population-weighted"
        return (f"Tract-level values supplied by {tc['source_label']} ({span}).{harm} {moe} County and "
                f"regional figures are derived from the tract values ({how}), not published by the source.")
    if indicator.get("source") == "viirs":
        return (f"Area-weighted mean nighttime-light radiance (nW/cm²/sr) per tract from the Earth "
                f"Observation Group's VIIRS annual composites ({span}). Higher values indicate more "
                f"artificial light at night (light pollution). A satellite measurement, not a survey, "
                f"so it carries no sampling margin of error.")
    if indicator.get("source") == "raster":
        return (f"Derived from the USGS National Land Cover Database ({span}), a 30-metre satellite "
                f"land-cover product. Tract values are area-weighted zonal statistics (exact pixel "
                f"fractions) of the classified raster. As a wall-to-wall classification it carries no "
                f"sampling margin of error.")
    if indicator.get("source") == "lodes":
        return (f"Workplace jobs from the Census Bureau's LEHD Origin-Destination Employment Statistics "
                f"(LODES8 Workplace Area Characteristics, {span}), summed from 2020 census blocks to "
                f"tracts. LODES is a synthetic, noise-infused full count rather than a survey sample, "
                f"so it carries no sampling margin of error.")
    if indicator.get("source") == "cdc_places":
        return (f"Model-based small-area estimates from the CDC PLACES project ({span}), which uses "
                f"BRFSS survey data and multilevel regression & poststratification to estimate adult "
                f"prevalence for every Census tract. Each estimate has a confidence interval; values "
                f"with high uncertainty are flagged.")
    return (f"Calculated from the U.S. Census Bureau's American Community Survey 5-Year Estimates "
            f"({span}), at the Census-tract level, with margins of error. ACS 5-year vintages overlap "
            f"year to year, so the series is a rolling estimate; compare only non-overlapping periods.")


def _meta_markdown(indicator: dict, years: list[int]) -> str:
    hib = indicator.get("higher_is_better")
    direction = ("A higher value is generally more favorable." if hib is True
                 else "A higher value generally signals greater need." if hib is False
                 else "Higher and lower values are not inherently better or worse.")
    span = f"{years[0]}–{years[-1]}" if years else ""
    label = _source_label(indicator)
    link = _source_link(indicator)
    short = label.split(',')[0].split(' (')[0]
    resource = f"- [{short}]({link})\n" if link else f"- {short}\n"
    return (f"## {indicator['label']}\n{indicator.get('description','')}\n\n"
            f"### Why is this important?\n{indicator.get('meta_why','').strip()} {direction}\n\n"
            f"### About the Data\n{_about_text(indicator, span)}\n\n_**Source**: {label}._\n\n"
            f"### Additional Resources\n{resource}")


def manifest_entry(indicator: dict, years: list[int]) -> dict:
    entry = {
        "id": indicator["id"], "slug": indicator["slug"], "label": indicator["label"],
        "description": indicator.get("description", ""), "category": indicator["theme"],
        "format": indicator.get("format", "number"), "decimals": indicator.get("decimals", 1),
        "higherIsBetter": indicator.get("higher_is_better"),
        "classMethod": "quantile", "years": years, "geoLevels": ["tract", "county"],
        "source": _source_label(indicator),
        "vintage": f"{years[0]}–{years[-1]}" if years else "",
        "metaPath": f"/data/meta/m{indicator['id']}.md",
        "related": [], "hasZ": True, "hasLisa": True,
    }
    if indicator.get("source") == "cdc_places":
        entry["crossReleaseTrend"] = True
        entry["trendNote"] = ("Model-based estimates from separate annual CDC PLACES releases — shown as "
                              "levels per year, not comparable over time (CDC advises against using them "
                              "to track local change).")
    if indicator.get("source") == "tract_csv":
        entry["countyMethod"] = "derived from tracts"
    return entry


def merge_into_app(indicator: dict, value_file: dict, z_doc: dict, lisa_doc: dict,
                   agg: dict, app_dir: Path):
    """Write value/analytics/meta and merge manifest + aggregates into the app data dir."""
    iid = indicator["id"]
    years = value_file["years"]
    (app_dir / "values").mkdir(parents=True, exist_ok=True)
    (app_dir / "analytics" / "z").mkdir(parents=True, exist_ok=True)
    (app_dir / "analytics" / "lisa").mkdir(parents=True, exist_ok=True)
    (app_dir / "meta").mkdir(parents=True, exist_ok=True)
    (app_dir / "values" / f"{iid}.json").write_text(json.dumps(value_file), encoding="utf-8")
    (app_dir / "analytics" / "z" / f"{iid}.json").write_text(json.dumps(z_doc), encoding="utf-8")
    (app_dir / "analytics" / "lisa" / f"{iid}.json").write_text(json.dumps(lisa_doc), encoding="utf-8")
    (app_dir / "meta" / f"m{iid}.md").write_text(_meta_markdown(indicator, years), encoding="utf-8")

    man_path = app_dir / "manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8"))
    cats = {c["key"] for c in man["categories"]}
    if indicator["theme"] not in cats:
        raise RuntimeError(f"theme {indicator['theme']!r} not a manifest category {sorted(cats)}")
    man["schemaVersion"] = SCHEMA_VERSION
    man["indicators"] = [i for i in man["indicators"] if i["id"] != iid] + [manifest_entry(indicator, years)]
    man["indicators"].sort(key=lambda i: i["id"])
    # top-level span shown on the data page: every year any indicator publishes
    man["years"] = sorted({y for i in man["indicators"] for y in i.get("years", [])})
    _atomic_write_text(man_path, json.dumps(man))

    agg_path = app_dir / "aggregates.json"
    aggregates = json.loads(agg_path.read_text(encoding="utf-8"))
    aggregates[str(iid)] = agg
    _atomic_write_text(agg_path, json.dumps(aggregates))


def write_contract(indicator: dict, value_file: dict, z_doc: dict, lisa_doc: dict, target: Path | None = None):
    base = target or EXPORT
    iid = indicator["id"]
    (base / "values").mkdir(parents=True, exist_ok=True)
    (base / "analytics" / "z").mkdir(parents=True, exist_ok=True)
    (base / "analytics" / "lisa").mkdir(parents=True, exist_ok=True)
    (base / "values" / f"{iid}.json").write_text(json.dumps(value_file), encoding="utf-8")
    (base / "analytics" / "z" / f"{iid}.json").write_text(json.dumps(z_doc), encoding="utf-8")
    (base / "analytics" / "lisa" / f"{iid}.json").write_text(json.dumps(lisa_doc), encoding="utf-8")

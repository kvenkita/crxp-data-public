"""Build a POPULATION-weighted 2010->2020 tract crosswalk for the region.

Method (pure tabular, auth-free + Census API):
  1. Stream the Census 2020<->2010 BLOCK relationship file; for each 2020 block keep the
     2010 block with the largest land-area overlap -> the 2020 block's 2010 tract.
  2. Pull 2020-census block population (dec/pl P1_001N) per county; each 2020 block's GEOID
     gives its 2020 tract.
  3. afact(t10 -> t20) = pop of 2020 blocks in (t10, t20) / pop of 2020 blocks in t10.
Output: data/tract_2010_2020_crosswalk_pop.csv  [t10, t20, afact]

Run once: python scripts/build_pop_crosswalk.py   (CENSUS_API_KEY in env)
"""
import os
import io
import sys
import glob
import zipfile
import requests
sys.path.insert(0, "src")
from crxp_data import config

ROOT = config.ROOT
OUT = ROOT / "data" / "tract_2010_2020_crosswalk_pop.csv"
SRC_DIR = ROOT / "data" / "raster"  # drop the Census block relationship files here (gitignored)
KEY = os.environ.get("CENSUS_API_KEY", "")


def _open_rel_streams():
    """Yield (name, text-stream) for each Census 2010<->2020 BLOCK relationship file (.zip or .txt)."""
    paths = sorted(glob.glob(str(SRC_DIR / "TAB2010_TAB2020*.zip"))
                   + glob.glob(str(SRC_DIR / "tab2010_tab2020*.txt")))
    for p in paths:
        if p.lower().endswith(".zip"):
            zf = zipfile.ZipFile(p)
            inner = zf.namelist()[0]
            yield os.path.basename(inner), io.TextIOWrapper(zf.open(inner), encoding="utf-8-sig")
        else:
            yield os.path.basename(p), open(p, encoding="utf-8-sig")


def block20_t10_area_shares(region):
    """Return {block20_geoid(15): {t10_tract(11): overlap land area}} from the Census block comparability
    file. A 2020 block can straddle several 2010 tracts; we keep ALL overlaps (by AREALAND_INT) so the
    block's population is apportioned fractionally across them — a dasymetric refinement over the prior
    winner-take-all assignment, which misallocated 100% of a split block's population to one side."""
    counties = {c["fips"] for c in region["counties"]}
    blocks = {}  # b20 -> {t10: area}
    found = False
    for name, fh in _open_rel_streams():
        found = True
        print(f"  reading {name} ...", flush=True)
        header = fh.readline().rstrip("\n").split("|")
        ix = {h: i for i, h in enumerate(header)}
        for line in fh:
            f = line.rstrip("\n").split("|")
            cnty20 = f[ix["STATE_2020"]] + f[ix["COUNTY_2020"]]
            if cnty20 not in counties:
                continue
            b20 = cnty20 + f[ix["TRACT_2020"]] + f[ix["BLK_2020"]]
            t10 = f[ix["STATE_2010"]] + f[ix["COUNTY_2010"]] + f[ix["TRACT_2010"]]
            try:
                area = float(f[ix["AREALAND_INT"]])
            except ValueError:
                continue
            if area <= 0:
                continue
            d = blocks.setdefault(b20, {})
            d[t10] = d.get(t10, 0.0) + area
        fh.close()
    if not found:
        raise SystemExit(
            "No block relationship files found in data/raster/ (expected TAB2010_TAB2020_ST*.zip). "
            "Download them from the Census 2020 relationship-files page.")
    return blocks


def block20_pop(region):
    """Return {block20_geoid(15): population} from the 2020 decennial (P1_001N)."""
    out = {}
    for c in region["counties"]:
        s, co = c["fips"][:2], c["fips"][2:]
        url = (f"https://api.census.gov/data/2020/dec/pl?get=P1_001N&for=block:*"
               f"&in=state:{s}%20county:{co}&key={KEY}")
        data = requests.get(url, timeout=120).json()
        idx = {h: i for i, h in enumerate(data[0])}
        for row in data[1:]:
            geo = row[idx["state"]] + row[idx["county"]] + row[idx["tract"]] + row[idx["block"]]
            try:
                out[geo] = float(row[idx["P1_001N"]])
            except (TypeError, ValueError):
                out[geo] = 0.0
    return out


def main():
    region = config.load_region()
    print("[1/3] block20 -> 2010 tract overlap shares (block relationship file) ...", flush=True)
    b20_shares = block20_t10_area_shares(region)
    print(f"      mapped {len(b20_shares):,} 2020 blocks", flush=True)
    print("[2/3] 2020 block populations ...", flush=True)
    pop = block20_pop(region)
    print(f"      {len(pop):,} blocks with population", flush=True)

    print("[3/3] apportion block pop across 2010 tracts (by overlap area) + normalize ...", flush=True)
    cell, tot = {}, {}
    for b20, shares in b20_shares.items():
        p = pop.get(b20, 0.0)
        area_tot = sum(shares.values())
        if p <= 0 or area_tot <= 0:
            continue
        t20 = b20[:11]
        for t10, area in shares.items():
            contrib = p * (area / area_tot)  # fractional apportionment, not winner-take-all
            cell[(t10, t20)] = cell.get((t10, t20), 0.0) + contrib
            tot[t10] = tot.get(t10, 0.0) + contrib
    rows = [(t10, t20, p / tot[t10]) for (t10, t20), p in cell.items() if tot.get(t10, 0) > 0]
    rows.sort()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as fh:
        fh.write("t10,t20,afact\n")
        for t10, t20, a in rows:
            fh.write(f"{t10},{t20},{round(a, 6)}\n")
    print(f"wrote {len(rows)} rows -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

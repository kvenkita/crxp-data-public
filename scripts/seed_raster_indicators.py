"""Generate config/indicators/*.yml for the NLCD raster Environment indicators (ids 70-74).
Re-runnable. Run: python scripts/seed_raster_indicators.py"""
from pathlib import Path
import yaml

OUT = Path(__file__).resolve().parents[1] / "config" / "indicators"
YEARS = [2001, 2004, 2006, 2008, 2011, 2013, 2016, 2019, 2021]  # legacy NLCD epochs (auth-free WCS)
LC = "mrlc_download__NLCD_{year}_Land_Cover_L48"
IMP = "mrlc_download__NLCD_{year}_Impervious_L48"


def lc(classes):
    return {"product": "nlcd_landcover", "coverage_template": LC, "years": YEARS, "stat": "classfrac",
            "classes": classes, "source_id": "nlcd"}


# (id, slug, label, hib, raster, desc, why)
S = [
    (70, "forest-cover", "Forest cover", None, lc([41, 42, 43]),
     "Share of land classified as forest (deciduous, evergreen, mixed)",
     "Forest cover indicates tree canopy, habitat, and natural land — and where it is being lost to development."),
    (71, "farmland", "Cropland & farmland", None, lc([81, 82]),
     "Share of land in agriculture (cultivated crops + pasture/hay)",
     "Agricultural land tracks the working rural landscape and its conversion to other uses."),
    (72, "wetlands", "Wetlands", None, lc([90, 95]),
     "Share of land classified as wetland (woody + emergent herbaceous)",
     "Wetlands provide flood control, water filtering, and habitat, and are sensitive to development."),
    (73, "developed-land", "Developed land", False, lc([21, 22, 23, 24]),
     "Share of land that is developed (open space through high intensity)",
     "Developed land captures the urban/built footprint and how fast it is expanding."),
    (74, "impervious-surface", "Impervious surface", False,
     {"product": "nlcd_impervious", "coverage_template": IMP, "years": YEARS, "stat": "mean", "source_id": "nlcd"},
     "Average share of surface that is impervious (pavement, rooftops)",
     "Impervious surface drives stormwater runoff, flooding, and the urban heat-island effect."),
]


def main():
    for iid, slug, label, hib, raster, desc, why in S:
        doc = {"id": iid, "slug": slug, "label": label, "theme": "environment",
               "format": "percent", "decimals": 1, "higher_is_better": hib,
               "source": "raster", "raster": raster, "description": desc, "meta_why": why}
        (OUT / f"{slug}.yml").write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    print(f"wrote {len(S)} raster indicator configs")


if __name__ == "__main__":
    main()

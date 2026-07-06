"""Generate config/indicators/*.yml for the original ACS indicators (ids 1-19, 21),
migrating them from the old static CSV into the pipeline (standard ACS tables + MOE).
Run once: python scripts/seed_acs_indicators.py  (re-runnable; overwrites these yml).
Private-school (13) is intentionally omitted (needs an ACS Subject table; see notes)."""
from pathlib import Path
import yaml

OUT = Path(__file__).resolve().parents[1] / "config" / "indicators"


def E(table, line):  # estimate var
    return f"{table}_{line}E"


def M(table, line):  # margin var
    return f"{table}_{line}M"


def prop(table, num_lines, den_line):
    return {
        "table": table, "kind": "proportion",
        "num_vars": [E(table, l) for l in num_lines],
        "num_moe_vars": [M(table, l) for l in num_lines],
        "den_var": E(table, den_line), "den_moe_var": M(table, den_line),
    }


# (id, slug, label, theme, higher_is_better, acs, description, why, [format])
SPECS = [
    # Character
    (1, "older-adults", "Older adults (65+)", "character", None,
     prop("B01001", ["020", "021", "022", "023", "024", "025", "044", "045", "046", "047", "048", "049"], "001"),
     "Share of residents aged 65 and older",
     "The share of older adults shapes demand for healthcare, accessible housing, transportation, and senior services."),
    (2, "youth", "Youth (under 18)", "character", None,
     prop("B01001", ["003", "004", "005", "006", "027", "028", "029", "030"], "001"),
     "Share of residents under age 18",
     "The youth share signals demand for schools, childcare, parks, and family services."),
    (21, "median-age", "Median age", "character", None,
     {"table": "B01002", "kind": "median", "estimate_var": E("B01002", "001"), "moe_var": M("B01002", "001")},
     "Median age of residents, in years",
     "Median age summarizes a neighborhood's age profile.", "years"),
    (3, "veterans", "Veterans", "character", None, prop("B21001", ["002"], "001"),
     "Share of civilian adults who are military veterans",
     "The veteran population helps target benefits, healthcare, and services for those who have served."),
    (4, "asian-residents", "Asian residents", "character", None, prop("B03002", ["006"], "001"),
     "Share of residents who are Asian (non-Hispanic)", "Racial/ethnic composition supports equity analysis."),
    (5, "black-residents", "Black residents", "character", None, prop("B03002", ["004"], "001"),
     "Share of residents who are Black or African American (non-Hispanic)", "Racial/ethnic composition supports equity analysis."),
    (6, "hispanic-residents", "Hispanic or Latino residents", "character", None, prop("B03002", ["012"], "001"),
     "Share of residents who are Hispanic or Latino", "Supports language access and equitable outreach."),
    (7, "white-residents", "White residents", "character", None, prop("B03002", ["003"], "001"),
     "Share of residents who are White (non-Hispanic)", "Racial/ethnic composition supports equity analysis."),
    (8, "other-race-residents", "Other races", "character", None, prop("B03002", ["005", "007", "008", "009"], "001"),
     "Share of residents of other or multiple races (non-Hispanic)", "Captures multiracial and other-race residents."),
    # Education
    (11, "bachelors-or-higher", "Bachelor's degree or higher", "education", True,
     prop("B15003", ["022", "023", "024", "025"], "001"),
     "Adults 25+ with a bachelor's degree or higher",
     "Educational attainment is strongly associated with earnings, health, and mobility."),
    (12, "high-school-diploma", "High school diploma or higher", "education", True,
     prop("B15003", ["017", "018", "019", "020", "021", "022", "023", "024", "025"], "001"),
     "Adults 25+ with at least a high school diploma", "High school completion is a foundational measure of opportunity."),
    # Economy
    (9, "employment", "Employment rate", "economy", True, prop("B23025", ["004"], "003"),
     "Share of the civilian labor force that is employed", "Reflects local economic health and household stability."),
    (10, "internet-access", "Households with internet access", "economy", True, prop("B28002", ["004"], "001"),
     "Households with a broadband internet subscription", "Home broadband is essential for school, work, and civic life."),
    # Housing
    (14, "owner-occupied", "Owner-occupied homes", "housing", True, prop("B25003", ["002"], "001"),
     "Occupied homes that are owner-occupied", "Homeownership is associated with wealth-building and stability."),
    (15, "occupied-homes", "Occupied homes", "housing", None, prop("B25002", ["002"], "001"),
     "Housing units that are occupied", "Occupancy reflects housing demand and vacancy."),
    (16, "vacant-homes", "Vacant homes", "housing", False, prop("B25002", ["003"], "001"),
     "Housing units that are vacant", "High vacancy can signal disinvestment or seasonal/rental turnover."),
    # Transportation
    (17, "no-vehicle", "Households without a vehicle", "transportation", False, prop("B08201", ["002"], "001"),
     "Households with no vehicle available", "Vehicle access affects reaching jobs, food, and care."),
    (18, "long-commute", "Commute over 20 minutes", "transportation", False,
     prop("B08303", ["006", "007", "008", "009", "010", "011", "012", "013"], "001"),
     "Workers with a commute of 20+ minutes", "Longer commutes cut into time, raise costs, and lower well-being."),
    (19, "drove-alone", "Drove alone to work", "transportation", None, prop("B08301", ["003"], "001"),
     "Workers who commute by driving alone", "Reflects car dependence, congestion, and emissions."),
]


def main():
    for spec in SPECS:
        iid, slug, label, theme, hib, acs, desc, why = spec[:8]
        fmt = spec[8] if len(spec) > 8 else "percent"
        doc = {
            "id": iid, "slug": slug, "label": label, "theme": theme,
            "format": fmt, "decimals": 1, "higher_is_better": hib,
            "source": "acs", "acs": acs, "description": desc, "meta_why": why,
        }
        (OUT / f"{slug}.yml").write_text(yaml.safe_dump(doc, sort_keys=False))
    print(f"wrote {len(SPECS)} ACS indicator configs to {OUT}")


if __name__ == "__main__":
    main()

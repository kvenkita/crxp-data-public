"""Generate config/indicators/*.yml for the second ACS batch (ids 50-64).
Re-runnable; overwrites these yml. Variable codes verified against ACS group metadata.
Run: python scripts/seed_acs_indicators2.py"""
from pathlib import Path
import yaml

OUT = Path(__file__).resolve().parents[1] / "config" / "indicators"


def lines(table, nums):
    return [f"{table}_{n}E" for n in nums], [f"{table}_{n}M" for n in nums]


def prop(table, num_lines, den_line=None, den_lines=None, kind="proportion", multiplier=None):
    nv, nm = lines(table, num_lines)
    acs = {"table": table, "kind": kind, "num_vars": nv, "num_moe_vars": nm}
    if den_lines:
        dv, dm = lines(table, den_lines)
        acs["den_vars"], acs["den_moe_vars"] = dv, dm
    else:
        acs["den_var"], acs["den_moe_var"] = f"{table}_{den_line}E", f"{table}_{den_line}M"
    if multiplier is not None:
        acs["multiplier"] = multiplier
    return acs


def passthrough(table, line, kind="median"):
    return {"table": table, "kind": kind, "estimate_var": f"{table}_{line}E", "moe_var": f"{table}_{line}M"}


# (id, slug, label, theme, hib, acs, fmt, decimals, desc, why)
S = []
S.append((50, "total-population", "Total population", "character", None,
          passthrough("B01003", "001", kind="count"), "number", 0,
          "Total resident population", "Population size is the denominator for most rates and the base measure of a community."))
A_DENS = passthrough("B01003", "001", kind="count"); A_DENS["per_land_area"] = True
S.append((51, "population-density", "Population density (per sq mi)", "character", None,
          A_DENS, "number", 0, "Residents per square mile of land area",
          "Density shapes transit viability, infrastructure cost, and the urban–rural character of a place."))
S.append((52, "average-household-size", "Average household size", "housing", None,
          passthrough("B25010", "001"), "number", 2, "Average number of people per occupied household",
          "Household size affects housing demand, school enrollment, and crowding."))
S.append((53, "households-with-children", "Households with children", "character", None,
          prop("B11005", ["002"], "001"), "percent", 1, "Households with one or more people under 18",
          "The share of households with children signals demand for schools, childcare, and family services."))
S.append((54, "households-with-seniors", "Households with seniors", "character", None,
          prop("B11007", ["002"], "001"), "percent", 1, "Households with one or more people 65+",
          "Households with seniors shape demand for accessible housing, healthcare, and aging services."))
S.append((55, "owner-cost-burden", "Owner cost burden", "housing", False,
          prop("B25091", ["008", "009", "010", "011", "019", "020", "021", "022"], "001"), "percent", 1,
          "Owner households paying 30%+ of income on housing costs",
          "Owner cost burden measures affordability stress among homeowners (with and without a mortgage)."))
S.append((56, "new-homes", "Homes built since 2010", "housing", None,
          prop("B25034", ["002", "003"], "001"), "percent", 1, "Housing units built in 2010 or later",
          "Recent construction marks where housing stock and population are growing fastest."))
S.append((57, "gini-index", "Income inequality (Gini)", "economy", False,
          passthrough("B19083", "001"), "number", 3, "Gini index of income inequality (0 = equal, 1 = unequal)",
          "The Gini index summarizes how unequally income is distributed within an area."))
S.append((58, "school-enrollment", "School enrollment (age 3+)", "education", None,
          prop("B14001", ["002"], "001"), "percent", 1, "Population age 3+ enrolled in school",
          "Enrollment reflects the share of residents in the education system, from preschool through college."))
S.append((59, "white-collar", "Management & professional occupations", "economy", None,
          prop("C24010", ["003", "039"], "001"), "percent", 1,
          "Employed residents in management, business, science, and arts occupations",
          "This Census major occupational group is the standard proxy for professional/managerial "
          "(“white-collar”) work used in labor and stratification research; it captures the "
          "professional-managerial class distinct from service, sales/office, and blue-collar work."))
S.append((60, "mean-travel-time", "Mean travel time to work (min)", "transportation", False,
          prop("B08013", ["001"], "001", kind="rate", multiplier=1.0) | {"den_var": "B08303_001E", "den_moe_var": "B08303_001M"},
          "number", 1, "Average one-way commute time for workers (minutes)",
          "Average commute time captures access to jobs and the daily time cost of the transportation system."))
S.append((61, "health-insurance", "Health insurance coverage", "health", True,
          prop("B27001", ["004", "007", "010", "013", "016", "019", "022", "025", "028",
                          "032", "035", "038", "041", "044", "047", "050", "053", "056"], "001"),
          "percent", 1, "Residents (all ages) with health insurance coverage",
          "Insurance coverage across all ages is a core measure of access to care and financial protection."))
S.append((62, "disability", "Disability (any)", "health", None,
          prop("B18101", ["004", "007", "010", "013", "016", "019", "023", "026", "029", "032", "035", "038"], "001"),
          "percent", 1, "Civilian noninstitutionalized residents with a disability",
          "Disability prevalence informs accessibility, services, and supports across the community."))
S.append((63, "foreign-born", "Foreign-born residents", "character", None,
          prop("B05012", ["003"], "001"), "percent", 1, "Residents born outside the United States",
          "The foreign-born share informs language access, immigrant services, and cultural diversity."))
S.append((64, "child-poverty", "Child poverty (families w/ children)", "economy", False,
          prop("B17010", ["004", "011", "017"],
               den_lines=["004", "011", "017", "024", "031", "037"]), "percent", 1,
          "Families with related children under 18 whose income is below poverty",
          "Child poverty among families with children is a sensitive measure of economic hardship affecting kids."))


def main():
    for iid, slug, label, theme, hib, acs, fmt, dec, desc, why in S:
        doc = {"id": iid, "slug": slug, "label": label, "theme": theme,
               "format": fmt, "decimals": dec, "higher_is_better": hib,
               "source": "acs", "acs": acs, "description": desc, "meta_why": why}
        (OUT / f"{slug}.yml").write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    print(f"wrote {len(S)} indicator configs")


if __name__ == "__main__":
    main()

from crxp_data import export_crxp


def _ind(**tc):
    base = {"path": "x.csv", "geoid_col": "G", "value_col": "V", "kind": "index", "year": 2023,
            "source_label": "FEMA National Risk Index v1.20",
            "source_url": "https://hazards.fema.gov/nri/"}
    base.update(tc)
    return {"id": 901, "slug": "hazard-risk", "label": "Hazard risk", "theme": "environment",
            "format": "number", "decimals": 1, "higher_is_better": False, "source": "tract_csv",
            "description": "Composite risk", "meta_why": "Hazards matter.", "tract_csv": base}


def test_manifest_uses_configured_label_and_marks_county_method():
    e = export_crxp.manifest_entry(_ind(), [2023])
    assert e["source"] == "FEMA National Risk Index v1.20"
    assert e["countyMethod"] == "derived from tracts"


def test_existing_sources_have_no_county_method():
    acs = {"id": 1, "slug": "a", "label": "A", "theme": "economy", "source": "acs"}
    assert "countyMethod" not in export_crxp.manifest_entry(acs, [2024])


def test_meta_credits_source_and_says_no_moe():
    md = export_crxp._meta_markdown(_ind(), [2023])
    assert "_**Source**: FEMA National Risk Index v1.20._" in md
    assert "(https://hazards.fema.gov/nri/)" in md
    assert "no margin of error" in md
    assert "population-weighted" in md


def test_meta_with_moe_and_2010_vintage():
    md = export_crxp._meta_markdown(_ind(moe_col="M", kind="count", tract_vintage=2010), [2019])
    assert "margins of error" in md and "flagged" in md
    assert "2010 census tracts" in md
    assert "summed" in md


def test_meta_without_url_lists_source_unlinked():
    ind = _ind()
    del ind["tract_csv"]["source_url"]
    md = export_crxp._meta_markdown(ind, [2023])
    assert "- FEMA National Risk Index v1.20\n" in md

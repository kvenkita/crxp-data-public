import pandas as pd
from crxp_data.sources import lodes
import pytest

REGION = {"counties": [{"fips": "37119"}, {"fips": "45091"}]}  # Mecklenburg NC, York SC

def test_aggregate_blocks_sums_to_tract_and_filters_region():
    # two blocks in Mecklenburg tract 37119000100, one in York tract 45091060100,
    # one OUT of region (Wake 37183...) that must be dropped.
    df = pd.DataFrame({
        "w_geocode": ["371190001001000", "371190001001001", "450910601001000", "371830500001000"],
        "C000":      [10,                 5,                  7,                 99],
        "CNS05":     [4,                  1,                  0,                 50],
    })
    out = lodes._aggregate_blocks(df, REGION)
    out = out.set_index("geoid")
    assert set(out.index) == {"37119000100", "45091060100"}   # Wake dropped
    assert out.loc["37119000100", "C000"] == 15               # 10 + 5
    assert out.loc["37119000100", "CNS05"] == 5               # 4 + 1
    assert out.loc["45091060100", "C000"] == 7


def test_industry_groups_and_core_measures():
    wac = pd.DataFrame({
        "geoid": ["37119000100"], "year": [2019], "C000": [100],
        "CNS09": [10], "CNS10": [10], "CNS11": [0], "CNS12": [10], "CNS13": [0],
        "CNS14": [0], "CNS20": [10],           # office = 40
        "CNS05": [20], "CNS06": [0], "CNS08": [10], "CNS03": [0], "CNS04": [0],  # industrial = 30
        "CE03": [50],
    })
    land = {"37119000100": 2.0}       # sq mi
    hh = {("37119000100", 2019): 25}  # households
    out = lodes.compute_measures(wac, region=None, land_area=land, households=hh)
    m = out.set_index("measure")["value"]
    assert m["total_jobs"] == 100
    assert m["job_density"] == 50.0            # 100 / 2.0
    assert m["jobs_housing_balance"] == 4.0    # 100 / 25
    assert m["office_share"] == 40.0           # 40/100 * 100
    assert m["industrial_share"] == 30.0
    assert m["high_wage_share"] == 50.0


def test_fetch_indicator_selects_one_measure(monkeypatch):
    wac = pd.DataFrame({"geoid": ["37119000100"], "year": [2019], "C000": [100]})
    monkeypatch.setattr(lodes, "wac_tracts", lambda region, years: wac)
    monkeypatch.setattr(lodes, "compute_measures",
                        lambda w, region, **kwargs: pd.DataFrame(
                            [{"geoid": "37119000100", "year": 2019, "measure": "total_jobs", "value": 100.0}]))
    ind = {"lodes": {"measure": "total_jobs", "years": [2019]}}
    out = lodes.fetch_indicator({"counties": []}, ind)
    assert list(out.columns) == ["geoid", "year", "value", "moe"]
    assert out.iloc[0]["value"] == 100.0 and out.iloc[0]["moe"] is None


def test_fetch_indicator_skips_households_for_non_balance(monkeypatch):
    wac = pd.DataFrame({"geoid": ["37119000100"], "year": [2019], "C000": [100]})
    monkeypatch.setattr(lodes, "wac_tracts", lambda region, years: wac)
    def boom(*a, **k): raise AssertionError("households must not be fetched for total_jobs")
    monkeypatch.setattr(lodes, "_households", boom)
    monkeypatch.setattr(lodes, "load_land_area", lambda region: {"37119000100": 2.0})
    ind = {"lodes": {"measure": "total_jobs", "years": [2019]}}
    out = lodes.fetch_indicator({"counties": []}, ind)
    assert out.iloc[0]["value"] == 100.0


def test_core_indicator_configs_load_with_unique_ids():
    from crxp_data import config
    ids = {}
    for slug in ("total-jobs", "job-density", "jobs-housing-balance"):
        ind = config.load_indicator(slug)
        assert ind["source"] == "lodes" and "measure" in ind["lodes"]
        ids[slug] = ind["id"]
    assert set(ids.values()) == {82, 83, 84}


def test_households_reads_acs_var_column(monkeypatch):
    """_households must read the ACS variable column (B25002_002E), not a 'value' column."""
    from crxp_data.sources import census_acs
    raw = pd.DataFrame({"geoid": ["37119000100"], "year": [2019], "B25002_002E": [42.0]})
    monkeypatch.setattr(census_acs, "resolve_provider", lambda region: "api")
    monkeypatch.setattr(census_acs, "_fetch_api", lambda region, var_ids, years: raw)
    hh = lodes._households({"counties": []}, [2019])
    assert hh == {("37119000100", 2019): 42.0}

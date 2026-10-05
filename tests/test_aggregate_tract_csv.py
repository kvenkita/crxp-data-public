import math
import pandas as pd
import pytest

from crxp_data import aggregate

REGION = {"counties": [{"fips": "37119"}, {"fips": "37025"}],
          "reliability": {"cv_caution": 15.0, "cv_unreliable": 30.0}}


def _ind(kind):
    return {"id": 999, "slug": "t", "source": "tract_csv",
            "tract_csv": {"kind": kind, "source_label": "T"}}


def _tracts(rows):
    return pd.DataFrame(rows, columns=["geoid", "year", "value", "moe"])


def _row(df, geoid):
    return df[df.geoid == geoid].iloc[0]


def test_count_sums_and_moe_in_quadrature():
    t = _tracts([("37119000100", 2023, 10.0, 3.0), ("37119000200", 2023, 20.0, 4.0),
                 ("37025000100", 2023, 5.0, None)])
    out = aggregate._tract_derived(_ind("count"), REGION, t, expected=set(t.geoid))
    meck = _row(out, "37119")
    assert meck.value == pytest.approx(30.0)
    assert meck.moe == pytest.approx(5.0)
    assert _row(out, aggregate.REGION_GEOID).value == pytest.approx(35.0)


def test_weighted_kinds_use_population():
    t = _tracts([("37119000100", 2023, 10.0, None), ("37119000200", 2023, 40.0, None)])
    pop = {("37119000100", 2023): 3000.0, ("37119000200", 2023): 1000.0}
    out = aggregate._tract_derived(_ind("index"), REGION, t, pop=pop)
    # (10*3000 + 40*1000) / 4000 = 17.5
    assert _row(out, "37119").value == pytest.approx(17.5)
    assert pd.isna(_row(out, "37119").moe)
    assert _row(out, "37119").reliability is None


def test_weighted_rollup_skips_tracts_without_pop():
    t = _tracts([("37119000100", 2023, 10.0, None), ("37119000200", 2023, 40.0, None)])
    pop = {("37119000100", 2023): 3000.0}            # second tract has no population
    out = aggregate._tract_derived(_ind("rate"), REGION, t, pop=pop)
    assert _row(out, "37119").value == pytest.approx(10.0)


def test_county_without_tracts_is_null_not_zero():
    t = _tracts([("37119000100", 2023, 10.0, None)])
    out = aggregate._tract_derived(_ind("count"), REGION, t)
    assert pd.isna(_row(out, "37025").value)


def test_build_county_region_dispatches_tract_csv(monkeypatch):
    t = _tracts([("37119000100", 2023, 1.0, None)])
    out = aggregate.build_county_region(_ind("count"), REGION, t, [2023])
    assert set(out.geoid) == {"37119", "37025", aggregate.REGION_GEOID}


def test_tract_population_uses_nearest_year(monkeypatch):
    wh = pd.DataFrame([("37119000100", 2019, 900.0, None, None, None),
                       ("37119000100", 2024, 1000.0, None, None, None)],
                      columns=["geoid", "year", "value", "moe", "cv", "reliability"])
    monkeypatch.setattr("crxp_data.warehouse.read_warehouse", lambda _id: wh)
    pop = aggregate.tract_population([2023, 2020])
    assert pop[("37119000100", 2023)] == 1000.0   # 2024 is nearer than 2019
    assert pop[("37119000100", 2020)] == 900.0


EXPECTED = {"37119000100", "37119000200", "37025000100"}


def test_count_total_needs_every_tract_in_the_county():
    # 37119 has two expected tracts but only one has a value -> no county total, no region total
    t = _tracts([("37119000100", 2023, 10.0, None), ("37025000100", 2023, 5.0, None)])
    out = aggregate._tract_derived(_ind("count"), REGION, t, expected=EXPECTED)
    assert pd.isna(_row(out, "37119").value)
    assert _row(out, "37025").value == pytest.approx(5.0)
    assert pd.isna(_row(out, aggregate.REGION_GEOID).value)


def test_count_suppressed_value_blocks_the_total():
    t = _tracts([("37119000100", 2023, 10.0, None), ("37119000200", 2023, None, None),
                 ("37025000100", 2023, 5.0, None)])
    out = aggregate._tract_derived(_ind("count"), REGION, t, expected=EXPECTED)
    assert pd.isna(_row(out, "37119").value)


def test_count_complete_county_sums():
    t = _tracts([("37119000100", 2023, 10.0, None), ("37119000200", 2023, 20.0, None),
                 ("37025000100", 2023, 5.0, None)])
    out = aggregate._tract_derived(_ind("count"), REGION, t, expected=EXPECTED)
    assert _row(out, "37119").value == pytest.approx(30.0)
    assert _row(out, aggregate.REGION_GEOID).value == pytest.approx(35.0)

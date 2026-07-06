import math
import pandas as pd
from crxp_data import harmonize


def _cw(rows):  # rows: (t10, t20, afact)
    return pd.DataFrame(rows, columns=["t10", "t20", "afact"])


def test_even_split_preserves_rate():
    # One 2010 tract A (20%, pop 1000) splits evenly into two 2020 tracts.
    raw = pd.DataFrame([{"geoid": "A", "year": 2019, "value": 20.0, "moe": 2.0, "pop": 1000.0}])
    cw = _cw([("A", "X", 0.5), ("A", "Y", 0.5)])
    out = harmonize.harmonize_places_rates(raw, cw, {2019}).sort_values("geoid").reset_index(drop=True)
    assert set(out.geoid) == {"X", "Y"}
    for v in out.value:
        assert abs(v - 20.0) < 1e-9
    for p in out["pop"]:
        assert abs(p - 500.0) < 1e-9


def test_merge_is_population_weighted():
    # Two 2010 tracts fully into one 2020 tract X -> pop-weighted blend of 10% and 30%.
    raw = pd.DataFrame([
        {"geoid": "A", "year": 2019, "value": 10.0, "moe": 1.0, "pop": 1000.0},
        {"geoid": "B", "year": 2019, "value": 30.0, "moe": 1.0, "pop": 3000.0},
    ])
    cw = _cw([("A", "X", 1.0), ("B", "X", 1.0)])
    out = harmonize.harmonize_places_rates(raw, cw, {2019}).reset_index(drop=True)
    assert len(out) == 1 and out.geoid.iloc[0] == "X"
    # (10*1000 + 30*3000) / 4000 = 25
    assert abs(out.value.iloc[0] - 25.0) < 1e-9
    assert abs(out["pop"].iloc[0] - 4000.0) < 1e-9


def test_non_vintage_years_pass_through():
    raw = pd.DataFrame([{"geoid": "Z", "year": 2023, "value": 5.0, "moe": 1.0, "pop": 500.0}])
    cw = _cw([("A", "X", 1.0)])
    out = harmonize.harmonize_places_rates(raw, cw, {2019})
    assert out.equals(raw)


def test_moe_combines_in_quadrature():
    # Two equal-pop tracts into X: case-MOEs add in quadrature, then back to a rate.
    raw = pd.DataFrame([
        {"geoid": "A", "year": 2019, "value": 10.0, "moe": 2.0, "pop": 1000.0},
        {"geoid": "B", "year": 2019, "value": 10.0, "moe": 2.0, "pop": 1000.0},
    ])
    cw = _cw([("A", "X", 1.0), ("B", "X", 1.0)])
    out = harmonize.harmonize_places_rates(raw, cw, {2019}).reset_index(drop=True)
    # casesM each = 2/100*1000 = 20 ; combined = sqrt(20^2+20^2)=28.284 ; rate moe = 100*28.284/2000
    assert abs(out.moe.iloc[0] - (100 * math.sqrt(800) / 2000)) < 1e-9

import math
import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from crxp_data import harmonize

# A 2010 tract A splits 60/40 into X,Y; B maps wholly into X.
CW = pd.DataFrame([
    {"t10": "A", "t20": "X", "afact": 0.6},
    {"t10": "A", "t20": "Y", "afact": 0.4},
    {"t10": "B", "t20": "X", "afact": 1.0},
])


def approx(a, b, tol=1e-3):
    return abs(a - b) <= tol


def test_count_allocation_and_moe():
    raw = pd.DataFrame([
        {"geoid": "A", "year": 2014, "POP_001E": 100.0, "POP_001M": 10.0},
        {"geoid": "B", "year": 2014, "POP_001E": 50.0, "POP_001M": 8.0},
    ])
    out = harmonize.to_2020_tracts(raw, CW, {"acs": {"kind": "proportion"}}, [2014])
    rec = {r.geoid: r for r in out.itertuples()}
    assert approx(rec["X"].POP_001E, 110.0)      # 100*0.6 + 50*1.0
    assert approx(rec["X"].POP_001M, 10.0)       # sqrt((10*.6)^2 + 8^2) = sqrt(36+64)
    assert approx(rec["Y"].POP_001E, 40.0)       # 100*0.4
    assert approx(rec["Y"].POP_001M, 4.0)


def test_median_is_weighted_average():
    raw = pd.DataFrame([
        {"geoid": "A", "year": 2019, "MED_001E": 200.0, "MED_001M": 20.0},
        {"geoid": "B", "year": 2019, "MED_001E": 100.0, "MED_001M": 10.0},
    ])
    out = harmonize.to_2020_tracts(raw, CW, {"acs": {"kind": "median"}}, [2019])
    rec = {r.geoid: r for r in out.itertuples()}
    assert approx(rec["X"].MED_001E, 220.0 / 1.6)   # (200*.6 + 100*1)/(.6+1)
    assert approx(rec["Y"].MED_001E, 200.0)


def test_non_vintage_years_pass_through():
    raw = pd.DataFrame([{"geoid": "37119000101", "year": 2024, "POP_001E": 5.0, "POP_001M": 1.0}])
    out = harmonize.to_2020_tracts(raw, CW, {"acs": {"kind": "proportion"}}, [2014, 2019])
    assert out.iloc[0]["geoid"] == "37119000101" and out.iloc[0]["POP_001E"] == 5.0

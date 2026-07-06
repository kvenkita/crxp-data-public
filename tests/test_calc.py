import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from crxp_data.indicators.calc import (
    cv_percent, reliability, agg_moe, ratio_moe, proportion_moe, significant_diff,
)


def approx(a, b, tol=1e-3):
    return abs(a - b) <= tol


def test_cv_percent():
    # se = 8225/1.645 = 5000; cv = 5000/50000 = 10%
    assert approx(cv_percent(50000, 8225), 10.0)
    assert math.isnan(cv_percent(0, 100))


def test_reliability_bands():
    assert reliability(10, 15, 30) == "ok"
    assert reliability(20, 15, 30) == "caution"
    assert reliability(40, 15, 30) == "unreliable"
    assert reliability(float("nan"), 15, 30) is None


def test_agg_moe():
    assert approx(agg_moe([3, 4]), 5.0)


def test_ratio_moe():
    # num=200(±30), den=1000(±50): r=0.2; moe=(1/1000)*sqrt(900+0.04*2500)=sqrt(1000)/1000
    assert approx(ratio_moe(200, 30, 1000, 50), math.sqrt(1000) / 1000)


def test_proportion_moe_and_fallback():
    # radicand positive: 900 - 0.04*2500 = 800
    assert approx(proportion_moe(200, 30, 1000, 50), math.sqrt(800) / 1000)
    # radicand negative -> ratio formula fallback
    val = proportion_moe(200, 10, 1000, 200)
    assert approx(val, ratio_moe(200, 10, 1000, 200))


def test_significant_diff():
    # diff 3000, se each 1000 -> stat 2.12 > 1.645 -> significant
    assert significant_diff(50000, 1645, 53000, 1645) is True
    # diff 500 -> not significant
    assert significant_diff(50000, 1645, 50500, 1645) is False
    assert significant_diff(50000, 1645, 53000, float("nan")) is None

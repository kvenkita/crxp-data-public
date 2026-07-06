"""Indicator calculation: MOE propagation, CV/reliability, comparable-period change.

Formulas follow the U.S. Census Bureau ACS guidance ("A Compass for Understanding
and Using ACS Data" / the ACS General Handbook). 90% MOE; SE = MOE / 1.645.
"""
from __future__ import annotations
import math

Z90 = 1.645


def se_from_moe(moe: float, z: float = Z90) -> float:
    return moe / z


def cv_percent(estimate: float, moe: float, z: float = Z90) -> float:
    """Coefficient of variation (%). NaN if not computable."""
    if estimate is None or moe is None:
        return float("nan")
    if not math.isfinite(estimate) or not math.isfinite(moe) or estimate == 0:
        return float("nan")
    return (se_from_moe(moe, z) / abs(estimate)) * 100.0


def reliability(cv: float, caution: float, unreliable: float) -> str | None:
    if cv is None or not math.isfinite(cv):
        return None
    if cv > unreliable:
        return "unreliable"
    if cv > caution:
        return "caution"
    return "ok"


def agg_moe(moes) -> float:
    """MOE of a sum of independent estimates: sqrt(sum of squares)."""
    vals = [m for m in moes if m is not None and math.isfinite(m)]
    return math.sqrt(sum(m * m for m in vals)) if vals else float("nan")


def ratio_moe(num: float, num_moe: float, den: float, den_moe: float) -> float:
    """MOE of a ratio R = num/den where num is NOT a subset of den."""
    if den == 0 or not all(math.isfinite(x) for x in (num, num_moe, den, den_moe)):
        return float("nan")
    r = num / den
    return (1.0 / den) * math.sqrt(num_moe ** 2 + (r ** 2) * den_moe ** 2)


def proportion_moe(num: float, num_moe: float, den: float, den_moe: float) -> float:
    """MOE of a proportion p = num/den where num IS a subset of den.

    Uses the Census proportion formula; if the radicand is negative, falls back
    to the ratio formula (per Census guidance).
    """
    if den == 0 or not all(math.isfinite(x) for x in (num, num_moe, den, den_moe)):
        return float("nan")
    p = num / den
    radicand = num_moe ** 2 - (p ** 2) * (den_moe ** 2)
    if radicand < 0:
        return ratio_moe(num, num_moe, den, den_moe)
    return (1.0 / den) * math.sqrt(radicand)


def significant_diff(e1: float, m1: float, e2: float, m2: float, z: float = Z90) -> bool | None:
    """Census statistical-significance test for the difference of two estimates (90%)."""
    if any(x is None or not math.isfinite(x) for x in (e1, m1, e2, m2)):
        return None
    denom = math.sqrt(se_from_moe(m1, z) ** 2 + se_from_moe(m2, z) ** 2)
    if denom == 0:
        return None
    return (abs(e1 - e2) / denom) > z


def _numerator_vars(acs, r):
    """Numerator (vars, moe_vars), honoring an optional per-vintage override.

    A few ACS tables redefine their category boundaries by vintage. B25034
    ("year structure built") is the case here: in the 2014 ACS5, _002 = "Built
    2010 or later" and _003 = "Built 2000 to 2009", but from 2015 on the two
    newest categories together span exactly "2010 or later". `num_vars_by_year`
    lets a config pick the right columns for the off-pattern vintage(s).
    """
    by_year = acs.get("num_vars_by_year")
    if by_year:
        try:
            y = int(r["year"])
        except (KeyError, TypeError, ValueError):
            y = None
        if y in by_year:
            return by_year[y], (acs.get("num_moe_vars_by_year") or {}).get(y, [])
    return acs["num_vars"], acs.get("num_moe_vars", [])


def _row_value_moe(r, acs, kind, fmt):
    """Assemble (value, moe) for one row from raw ACS variable columns."""
    if kind in ("median", "count", "number"):
        return r.get(acs["estimate_var"]), r.get(acs.get("moe_var"))
    if kind in ("proportion", "rate"):
        num_vars, num_moe_vars = _numerator_vars(acs, r)
        num = sum(r.get(v, float("nan")) for v in num_vars)
        num_moe = agg_moe([r.get(v, float("nan")) for v in num_moe_vars])
        if acs.get("den_vars"):                       # summed denominator
            den = sum(r.get(v, float("nan")) for v in acs["den_vars"])
            den_moe = agg_moe([r.get(v, float("nan")) for v in acs.get("den_moe_vars", [])])
        else:
            den, den_moe = r.get(acs["den_var"]), r.get(acs.get("den_moe_var"))
        if den is None or not math.isfinite(den) or den == 0:
            return float("nan"), float("nan")
        p = num / den
        pm = proportion_moe(num, num_moe, den, den_moe) if kind == "proportion" else ratio_moe(num, num_moe, den, den_moe)
        mult = 100.0 if fmt == "percent" else acs.get("multiplier", 1.0)
        return p * mult, pm * mult
    raise ValueError(f"unknown acs.kind {kind!r}")


def add_reliability(df, region: dict):
    """For sources that already provide value + moe (e.g. CDC PLACES): add cv + reliability."""
    import pandas as pd
    caution = region["reliability"]["cv_caution"]
    unreliable = region["reliability"]["cv_unreliable"]
    rows = []
    for r in df.itertuples():
        value, moe = r.value, r.moe
        cv = cv_percent(value, moe)
        rows.append({
            "geoid": r.geoid, "year": int(r.year),
            "value": None if (value is None or not math.isfinite(value)) else round(value, 4),
            "moe": None if (moe is None or not math.isfinite(moe)) else round(moe, 4),
            "cv": None if not math.isfinite(cv) else round(cv, 2),
            "reliability": reliability(cv, caution, unreliable),
        })
    return pd.DataFrame(rows)


def compute_indicator(df, indicator: dict, region: dict):
    """Compute value/moe/cv/reliability per tract-year from raw ACS variable columns.

    Returns [geoid, year, value, moe, cv, reliability]."""
    import pandas as pd
    acs = indicator["acs"]
    kind = acs.get("kind", "median")
    fmt = indicator.get("format", "number")
    caution = region["reliability"]["cv_caution"]
    unreliable = region["reliability"]["cv_unreliable"]

    rows = []
    for _, r in df.iterrows():
        value, moe = _row_value_moe(r, acs, kind, fmt)
        cv = cv_percent(value, moe)
        rows.append({
            "geoid": r["geoid"], "year": int(r["year"]),
            "value": None if (value is None or not math.isfinite(value)) else round(value, 4),
            "moe": None if (moe is None or not math.isfinite(moe)) else round(moe, 4),
            "cv": None if not math.isfinite(cv) else round(cv, 2),
            "reliability": reliability(cv, caution, unreliable),
        })
    return pd.DataFrame(rows)

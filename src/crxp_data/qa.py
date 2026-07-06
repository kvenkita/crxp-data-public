"""Build-time QA gate.

Fails the build (raises QAError) rather than silently publishing corrupt data. Catches the
catastrophic cases — a year that came back mostly empty, a collapse in tract coverage, or values
outside a configured plausible range — not normal ACS sparsity. Thresholds are lenient by design and
overridable per indicator via the optional `qa:` block in its config.
"""
from __future__ import annotations
import math


class QAError(RuntimeError):
    pass


def _finite(xs):
    return [x for x in xs if x is not None and isinstance(x, (int, float)) and math.isfinite(x)]


def check_tidy(tidy, *, expected_geoids, years, value_range=None,
               max_null_rate=0.7, min_geoid_coverage=0.5, label="indicator"):
    """Validate a computed tidy frame (columns geoid, year, value, ...) before warehousing.

    - geoid coverage: each present year must cover >= min_geoid_coverage of the expected tract set
    - null rate: each present year must have <= max_null_rate null/non-finite values
    - value range (optional): finite values must lie within [lo, hi]

    Years in `years` that are absent from the frame are ignored here (a legitimately skipped vintage
    is handled upstream). Raises QAError listing all problems; returns a per-year report on success.
    """
    expected = set(expected_geoids)
    n_expected = len(expected) or 1
    present_years = sorted({int(y) for y in tidy["year"].unique()})
    report, problems = {}, []
    for y in years:
        if y not in present_years:
            continue
        sub = tidy[tidy["year"] == y]
        n = len(sub)
        cov = len(set(sub["geoid"]) & expected) / n_expected
        vals = _finite(list(sub["value"]))
        null_rate = 1 - (len(vals) / n) if n else 1.0
        if cov < min_geoid_coverage:
            problems.append(f"{y}: geoid coverage {cov:.0%} < {min_geoid_coverage:.0%}")
        if null_rate > max_null_rate:
            problems.append(f"{y}: null rate {null_rate:.0%} > {max_null_rate:.0%}")
        if value_range and vals:
            lo, hi = value_range
            oob = [v for v in vals if v < lo or v > hi]
            if oob:
                problems.append(f"{y}: {len(oob)} values outside [{lo},{hi}] (e.g. {oob[0]})")
        report[y] = {"coverage": round(cov, 3), "null_rate": round(null_rate, 3), "n": n}
    if problems:
        raise QAError(f"QA gate failed for {label}: " + "; ".join(problems))
    return report

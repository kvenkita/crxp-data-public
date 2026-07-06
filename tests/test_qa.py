import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd
import pytest

from crxp_data.qa import check_tidy, QAError

GEOIDS = [f"37119{i:06d}" for i in range(100)]  # 100 expected tracts


def _frame(years, coverage=1.0, null_rate=0.0, value=10.0):
    n = int(len(GEOIDS) * coverage)
    rows = []
    for y in years:
        for i, g in enumerate(GEOIDS[:n]):
            v = None if (i / n) < null_rate else value
            rows.append({"geoid": g, "year": y, "value": v})
    return pd.DataFrame(rows)


def test_clean_frame_passes():
    rep = check_tidy(_frame([2019, 2024]), expected_geoids=GEOIDS, years=[2019, 2024])
    assert set(rep) == {2019, 2024}
    assert rep[2024]["coverage"] == 1.0


def test_low_coverage_fails():
    with pytest.raises(QAError, match="coverage"):
        check_tidy(_frame([2024], coverage=0.2), expected_geoids=GEOIDS, years=[2024])


def test_high_null_rate_fails():
    with pytest.raises(QAError, match="null rate"):
        check_tidy(_frame([2024], null_rate=0.9), expected_geoids=GEOIDS, years=[2024])


def test_out_of_range_fails():
    with pytest.raises(QAError, match="outside"):
        check_tidy(_frame([2024], value=999.0), expected_geoids=GEOIDS, years=[2024],
                   value_range=(0, 100))


def test_absent_year_is_ignored():
    # asking about 2014 when the frame only has 2024 should not fail (skipped vintage handled upstream)
    rep = check_tidy(_frame([2024]), expected_geoids=GEOIDS, years=[2014, 2024])
    assert set(rep) == {2024}

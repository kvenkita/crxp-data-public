import math
import pandas as pd
import pytest

from crxp_data.sources import tract_csv
from crxp_data.sources.tract_csv import TractCsvConfigError

COUNTIES = {"37119", "37025"}


def _ind(**tc):
    base = {"path": "x.csv", "geoid_col": "GEOID", "value_col": "VAL", "kind": "index",
            "year": 2023, "source_label": "Test Source"}
    base.update(tc)
    return {"id": 999, "slug": "test-ind", "source": "tract_csv", "tract_csv": base}


def _df(rows):
    return pd.DataFrame(rows)


def test_pads_and_filters_to_region():
    df = _df([{"GEOID": "37119000100", "VAL": 5.0},
              {"GEOID": "37025000200", "VAL": 7.0},
              {"GEOID": "45091000100", "VAL": 9.0}])          # not a region county here
    out = tract_csv.normalize(df, _ind(), COUNTIES)
    assert sorted(out.geoid) == ["37025000200", "37119000100"]
    assert set(out.year) == {2023}
    assert out.moe.isna().all()


def test_geoid_float_and_short_forms():
    df = _df([{"GEOID": "37119000100.0", "VAL": 1.0},
              {"GEOID": " 37025000200 ", "VAL": 2.0}])
    out = tract_csv.normalize(df, _ind(), COUNTIES)
    assert sorted(out.geoid) == ["37025000200", "37119000100"]
    short = tract_csv.normalize(_df([{"GEOID": "1001020100", "VAL": 3.0}]), _ind(), {"01001"})
    assert short.geoid.tolist() == ["01001020100"]


def test_year_col_and_moe_col():
    df = _df([{"GEOID": "37119000100", "VAL": 10.0, "M": 2.0, "YR": 2021},
              {"GEOID": "37119000100", "VAL": 11.0, "M": 2.5, "YR": 2022}])
    ind = _ind(moe_col="M", year_col="YR")
    del ind["tract_csv"]["year"]
    out = tract_csv.normalize(df, ind, COUNTIES).sort_values("year")
    assert out.year.tolist() == [2021, 2022]
    assert out.moe.tolist() == [2.0, 2.5]


def test_missing_column_named_in_error():
    with pytest.raises(TractCsvConfigError, match="VAL"):
        tract_csv.normalize(_df([{"GEOID": "37119000100", "OTHER": 1}]), _ind(), COUNTIES)


def test_no_region_rows_is_an_error():
    with pytest.raises(TractCsvConfigError, match="no rows matched"):
        tract_csv.normalize(_df([{"GEOID": "06001400100", "VAL": 1.0}]), _ind(), COUNTIES)


def test_duplicate_geoid_year_rejected():
    df = _df([{"GEOID": "37119000100", "VAL": 1.0}, {"GEOID": "37119000100", "VAL": 2.0}])
    with pytest.raises(TractCsvConfigError, match="duplicate"):
        tract_csv.normalize(df, _ind(), COUNTIES)


@pytest.mark.parametrize("bad, msg", [
    ({"kind": "mean"}, "kind"),
    ({"source_label": None}, "source_label"),
    ({"tract_vintage": 2000}, "tract_vintage"),
    ({"year_col": "YR"}, "exactly one"),                        # both year and year_col
    ({"tract_vintage": 2010, "kind": "median"}, "cannot be allocated"),
    ({"tract_vintage": 2010, "kind": "index"}, "cannot be allocated"),
    ({"tract_vintage": 2010, "kind": "rate"}, "pop_col"),
])
def test_spec_rejects_bad_config(bad, msg):
    with pytest.raises(TractCsvConfigError, match=msg):
        tract_csv.spec(_ind(**bad))


def _cw():
    # 2010 tract A splits 50/50 into X, Y; 2010 tract B goes wholly to Y
    return pd.DataFrame([("A", "X", 0.5), ("A", "Y", 0.5), ("B", "Y", 1.0)],
                        columns=["t10", "t20", "afact"])


def test_2010_count_allocation():
    df = pd.DataFrame([{"geoid": "A", "year": 2019, "value": 100.0, "moe": 10.0},
                       {"geoid": "B", "year": 2019, "value": 40.0, "moe": 4.0}])
    out = tract_csv.allocate_2010(df, _cw(), "count").set_index("geoid")
    assert out.loc["X", "value"] == pytest.approx(50.0)
    assert out.loc["Y", "value"] == pytest.approx(90.0)
    assert out.loc["Y", "moe"] == pytest.approx(math.sqrt(5.0 ** 2 + 4.0 ** 2))


def test_2010_rate_allocation_is_pop_weighted():
    df = pd.DataFrame([{"geoid": "A", "year": 2019, "value": 10.0, "moe": 1.0, "pop": 1000.0},
                       {"geoid": "B", "year": 2019, "value": 30.0, "moe": 1.0, "pop": 500.0}])
    out = tract_csv.allocate_2010(df, _cw(), "rate").set_index("geoid")
    assert out.loc["X", "value"] == pytest.approx(10.0)
    # Y = (10% * 500 + 30% * 500) / 1000 = 20%
    assert out.loc["Y", "value"] == pytest.approx(20.0)


def test_2010_rate_without_moe_stays_null():
    df = pd.DataFrame([{"geoid": "A", "year": 2019, "value": 10.0, "moe": float("nan"), "pop": 1000.0}])
    out = tract_csv.allocate_2010(df, _cw(), "rate")
    assert out.moe.isna().all()


def test_fetch_indicator_reads_absolute_path(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("GEOID,VAL\n37119000100,4.5\n37119000200,5.5\n", encoding="utf-8")
    region = {"counties": [{"fips": "37119"}]}
    cw = pd.DataFrame([("37119000100", "37119000100", 1.0), ("37119000200", "37119000200", 1.0)],
                      columns=["t10", "t20", "afact"])
    out = tract_csv.fetch_indicator(region, _ind(path=str(p)), crosswalk=cw)
    assert list(out.columns) == ["geoid", "year", "value", "moe"]
    assert out.value.tolist() == [4.5, 5.5]


def _vintage_cw():
    # 2010 tracts A10, B10 (B10 split in 2020 into B1, B2); A kept its id across vintages.
    return pd.DataFrame([("37119000100", "37119000100", 1.0),
                         ("37119000200", "37119000201", 0.5),
                         ("37119000200", "37119000202", 0.5)], columns=["t10", "t20", "afact"])


def _csv(tmp_path, geoids):
    p = tmp_path / "v.csv"
    p.write_text("GEOID,VAL\n" + "".join(f"{g},1.0\n" for g in geoids), encoding="utf-8")
    return str(p)


REGION_V = {"counties": [{"fips": "37119"}]}


def test_2010_file_declared_2020_is_rejected_with_hint(tmp_path):
    path = _csv(tmp_path, ["37119000100", "37119000200"])          # 2010 ids
    with pytest.raises(TractCsvConfigError, match="tract_vintage: 2010"):
        tract_csv.fetch_indicator(REGION_V, _ind(path=path), crosswalk=_vintage_cw())


def test_2020_file_declared_2010_is_rejected_with_hint(tmp_path):
    path = _csv(tmp_path, ["37119000100", "37119000201", "37119000202"])   # 2020 ids
    ind = _ind(path=path, kind="count", tract_vintage=2010)
    with pytest.raises(TractCsvConfigError, match="tract_vintage: 2020"):
        tract_csv.fetch_indicator(REGION_V, ind, crosswalk=_vintage_cw())


def test_matching_vintage_passes(tmp_path):
    path = _csv(tmp_path, ["37119000100", "37119000201", "37119000202"])
    out = tract_csv.fetch_indicator(REGION_V, _ind(path=path), crosswalk=_vintage_cw())
    assert len(out) == 3

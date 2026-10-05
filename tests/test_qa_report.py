import json
import pandas as pd
import pytest

from crxp_data import qa
from crxp_data.qa import QAError

GEOIDS = [f"37119{i:06d}" for i in range(10)]


def _tidy(value=10.0, n=10, years=(2024,)):
    return pd.DataFrame([{"geoid": g, "year": y, "value": value}
                         for y in years for g in GEOIDS[:n]])


def _ind(slug="a", iid=1, **kw):
    return {"id": iid, "slug": slug, "label": slug.upper(), "source": "acs", **kw}


def test_pass_writes_json_and_summary(tmp_path):
    rep = qa.run_and_record(_ind(), _tidy(), GEOIDS, out_dir=tmp_path, checked_on="2026-10-05")
    assert 2024 in rep
    doc = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    assert doc["status"] == "pass" and doc["years"]["2024"]["coverage"] == 1.0
    md = (tmp_path / "qa_report.md").read_text(encoding="utf-8")
    assert "| 1 | A | acs | 2024–2024 (1) | 100.0% | 0.0% | — | PASS |" in md
    assert "1 indicators checked; 0 failed." in md


def test_fail_writes_report_then_raises(tmp_path):
    with pytest.raises(QAError) as ei:
        qa.run_and_record(_ind(qa={"range": [0, 5]}), _tidy(value=99.0), GEOIDS,
                          out_dir=tmp_path, checked_on="2026-10-05")
    assert ei.value.problems and ei.value.report[2024]["n"] == 10
    doc = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    assert doc["status"] == "fail" and doc["range"] == [0, 5]
    assert "FAIL" in (tmp_path / "qa_report.md").read_text(encoding="utf-8")


def test_summary_sorted_by_id_and_lists_failures(tmp_path):
    qa.write_report(_ind("b", 2), {2024: {"coverage": 0.4, "null_rate": 0.0, "n": 4}},
                    ["2024: geoid coverage 40% < 50%"], value_range=None,
                    checked_on="d", out_dir=tmp_path)
    qa.write_report(_ind("a", 1), {2024: {"coverage": 1.0, "null_rate": 0.0, "n": 10}}, [],
                    value_range=None, checked_on="d", out_dir=tmp_path)
    md = qa.render_summary(tmp_path, "2026-10-05").read_text(encoding="utf-8")
    assert md.index("| 1 | A") < md.index("| 2 | B")
    assert "- **b**: 2024: geoid coverage 40% < 50%" in md


def test_main_all_over_fixture_warehouse(tmp_path, monkeypatch):
    import crxp_data.config as config
    import crxp_data.geo as geo
    import crxp_data.warehouse as wh
    inds = {"a": _ind("a", 1), "b": _ind("b", 2)}
    monkeypatch.setattr(config, "list_indicators", lambda: ["a", "b"])
    monkeypatch.setattr(config, "load_indicator", lambda s: inds[s])
    monkeypatch.setattr(geo, "load_tract_centroids", lambda: {g: (0, 0) for g in GEOIDS})
    monkeypatch.setattr(wh, "read_warehouse", lambda i: _tidy() if i == 1 else None)
    code = qa.main(["--all"], out_dir=tmp_path)
    assert code == 1                                   # b has no warehouse rows
    md = (tmp_path / "qa_report.md").read_text(encoding="utf-8")
    assert "2 indicators checked; 1 failed." in md
    assert "- **b**: no warehouse rows" in md


def test_main_requires_all_flag():
    with pytest.raises(SystemExit):
        qa.main([])

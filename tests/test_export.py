import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from crxp_data import export_crxp

IND = {"id": 99, "format": "dollar", "acs": {"kind": "median"}}


def _df():
    rows = []
    for g in ("37119000100", "37119000200", "37119000300"):
        for y, v, m in ((2019, 40000, 5000), (2024, 50000, 6000)):
            rows.append({"geoid": g, "year": y, "value": v, "moe": m, "cv": 10.0, "reliability": "ok"})
    return pd.DataFrame(rows)


def test_build_value_file_shape_matches_contract():
    vf = export_crxp.build_value_file(IND, _df(), [2019, 2024])
    assert vf["indicatorId"] == 99
    assert vf["years"] == [2019, 2024]
    # every value row aligns to years length (the app/validator requirement)
    for g, arr in vf["values"].items():
        assert len(arr) == len(vf["years"])
        assert len(vf["moe"][g]) == len(vf["years"])     # MOE carried per geoid/year
        assert len(vf["cv"][g]) == len(vf["years"])
    # per-year stats include breaks + min/max/p1/p99 (build-data gate)
    for y in ("2019", "2024"):
        s = vf["stats"][y]
        assert set(["min", "max", "p1", "p99", "breaks"]).issubset(s)
    assert "domain" in vf and "breaks" in vf

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from crxp_data.geo import load_tract_centroids
from crxp_data.config import ROOT


def test_representative_point_is_inside_l_shaped_tract(tmp_path):
    """A bbox midpoint can fall in the notch of an L-shaped polygon (outside it); the
    representative point must always be inside — it's what feeds the kNN/LISA spatial weights."""
    shapely_geom = pytest.importorskip("shapely.geometry")
    ring = [[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2], [0, 0]]  # an "L"
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "X", "properties": {"geoid": "X"},
         "geometry": {"type": "Polygon", "coordinates": [ring]}}]}
    p = tmp_path / "t.geojson"
    p.write_text(json.dumps(fc))

    cents = load_tract_centroids(p)
    poly = shapely_geom.shape(fc["features"][0]["geometry"])
    assert poly.contains(shapely_geom.Point(*cents["X"]))
    # the bbox midpoint (1,1) is the reflex vertex — on the boundary, NOT strictly interior
    assert not poly.contains(shapely_geom.Point(1, 1))


def test_pop_crosswalk_afacts_sum_to_one_per_t10():
    """Invariant: each 2010 tract's allocation factors sum to ~1 (re-normalized after apportionment)."""
    import pandas as pd
    csv = ROOT / "data" / "tract_2010_2020_crosswalk_pop.csv"
    if not csv.exists():
        pytest.skip("population crosswalk not built")
    df = pd.read_csv(csv, dtype={"t10": str, "t20": str})
    sums = df.groupby("t10")["afact"].sum()
    assert (sums - 1.0).abs().max() < 0.01

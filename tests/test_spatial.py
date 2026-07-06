import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import random

from crxp_data.spatial import (
    zscores, quantile_breaks, summarize, knn_weights, local_moran, benjamini_hochberg, LISA,
)


def test_zscores_mean0_sd1():
    z = zscores([1, 2, 3, 4, 5])
    assert abs(sum(z) / len(z)) < 1e-9
    assert z[0] < 0 < z[-1]
    assert zscores([1, None, 3])[1] is None


def test_quantile_breaks_increasing():
    b = quantile_breaks(list(range(1, 11)), 5)
    assert len(b) == 4
    assert all(b[i] > b[i - 1] for i in range(1, len(b)))


def test_summarize():
    s = summarize(list(range(0, 101, 10)), 5)
    assert s["min"] == 0 and s["max"] == 100 and s["p99"] > 90


def test_local_moran_hh_cluster():
    pts, obs = [], []
    for r in range(8):
        for c in range(8):
            gid = f"{r}_{c}"
            pts.append((gid, c, r))
            high = r < 3 and c < 3
            obs.append((gid, 100 + r + c if high else 1 + r + c))
    w = knn_weights(pts, 4)
    res = local_moran(obs, w, perms=499, seed=42)
    # an interior cell of the strong high-value block is a significant HH cluster
    assert res["0_0"]["quadrant"] == LISA["HH"]
    assert res["0_0"]["sig"] is True


def test_benjamini_hochberg_step_up():
    # one tiny p, rest large: BH should pick the smallest under k/m*alpha
    pvals = [("a", 0.001), ("b", 0.6), ("c", 0.7), ("d", 0.8), ("e", 0.9)]
    sig = benjamini_hochberg(pvals, alpha=0.05)
    assert sig == {"a"}
    # all null -> none significant
    assert benjamini_hochberg([("x", 0.4), ("y", 0.5)], 0.05) == set()
    # all significant when every p is tiny
    assert benjamini_hochberg([("x", 0.0001), ("y", 0.0002)], 0.05) == {"x", "y"}


def test_local_moran_false_positive_rate_under_randomness():
    """Spatially random data should yield FEW significant tracts after FDR (false-positive control).
    The pre-fix null (with-replacement, no FDR) lit up far more; this guards the correction."""
    rng = random.Random(7)
    pts, obs = [], []
    for r in range(12):
        for c in range(12):
            gid = f"{r}_{c}"
            pts.append((gid, c, r))
            obs.append((gid, rng.gauss(0, 1)))  # no spatial structure
    w = knn_weights(pts, 8)
    res = local_moran(obs, w, perms=499, seed=1)
    n = len(obs)
    n_sig = sum(1 for v in res.values() if v["sig"])
    # under randomness, BH-FDR should keep significant discoveries to a small fraction
    assert n_sig <= 0.05 * n + 2

import sys
import math
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
    res = local_moran(obs, w, seed=42)
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


def test_permutation_draws_are_without_replacement():
    import numpy as np
    from crxp_data.spatial import _draws_without_replacement
    rng = np.random.default_rng(0)
    for n, k in [(751, 8), (10, 8), (5, 5)]:
        d = _draws_without_replacement(rng, n, k, 2000)
        assert d.shape == (2000, k) and d.min() >= 0 and d.max() < n
        assert all(len(set(row)) == k for row in d.tolist())


def test_default_permutations_clear_the_fdr_floor():
    """With ~752 tracts, BH at alpha=0.05 can only reject when the pseudo-p floor 1/(perms+1) is at or
    below r*alpha/m for a small r; 999 permutations needed >= 15 tracts at the floor (the bug)."""
    import inspect
    perms = inspect.signature(local_moran).parameters["perms"].default
    m, alpha = 752, 0.05
    r_needed = math.ceil((1 / (perms + 1)) * m / alpha)
    assert r_needed <= 2


def test_rank_normal_scores():
    from crxp_data.spatial import rank_normal
    out = rank_normal([3.0, None, 1.0, 2.0, 2.0, 1000.0])
    assert out[1] is None
    # monotone in the input, ties share a score
    assert out[2] < out[3] == out[4] < out[0] < out[5]
    assert out[5] < 1.5  # the extreme value is bounded by its rank


def test_lisa_finds_cluster_despite_extreme_outlier():
    """A skewed indicator: a clear high block plus one extreme outlier elsewhere. On raw values the
    outlier inflates the null; the rank-normal default still detects the block."""
    pts, obs = [], []
    for r in range(20):
        for c in range(20):
            gid = f"{r}_{c}"
            pts.append((gid, c, r))
            v = 10.0 + (r * 20 + c) % 7 * 0.1
            if r < 6 and c < 6:
                v = 20.0 + (r + c) * 0.1
            if (r, c) == (17, 17):
                v = 500.0
            obs.append((gid, v))
    w = knn_weights(pts, 8)
    res = local_moran(obs, w, perms=999, seed=3)
    assert sum(1 for g, v in res.items() if v["sig"] and v["quadrant"] == LISA["HH"]) >= 10

"""Spatial + descriptive statistics, ported from the CRXP app's spatial.js so the
pipeline produces the analytics the app currently computes (z, breaks, LISA)."""
from __future__ import annotations
import math

import numpy as np

LISA = {"NS": 0, "HH": 1, "LH": 2, "LL": 3, "HL": 4}


def _finite(values):
    return [v for v in values if v is not None and isinstance(v, (int, float)) and math.isfinite(v)]


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


def std(xs):
    xs = list(xs)
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def zscores(values):
    fin = _finite(values)
    m, s = mean(fin), std(fin)
    return [
        ((v - m) / s) if (v is not None and isinstance(v, (int, float)) and math.isfinite(v) and s > 0) else None
        for v in values
    ]


def percentile_sorted(sorted_vals, p):
    n = len(sorted_vals)
    if n == 0:
        return float("nan")
    if p <= 0:
        return sorted_vals[0]
    if p >= 1:
        return sorted_vals[-1]
    idx = p * (n - 1)
    lo, hi = math.floor(idx), math.ceil(idx)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def quantile_breaks(values, n=5):
    s = sorted(_finite(values))
    if not s:
        return []
    breaks = [percentile_sorted(s, i / n) for i in range(1, n)]
    out = []
    for i, b in enumerate(breaks):
        if i == 0 or b > out[-1]:
            out.append(b)
    return out


def summarize(values, classes=5):
    s = sorted(_finite(values))
    if not s:
        return {"min": 0, "max": 0, "p1": 0, "p99": 0, "breaks": []}
    return {
        "min": s[0], "max": s[-1],
        "p1": percentile_sorted(s, 0.01), "p99": percentile_sorted(s, 0.99),
        "breaks": quantile_breaks(values, classes),
    }


def knn_weights(points, k=8):
    """points: list of (id, x, y). Returns {id: [(id, w), ...]} row-standardized."""
    weights = {}
    for aid, ax, ay in points:
        dists = []
        for bid, bx, by in points:
            if aid == bid:
                continue
            dx, dy = ax - bx, ay - by
            dists.append((dx * dx + dy * dy, bid))
        dists.sort()
        nn = dists[: min(k, len(dists))]
        w = 1.0 / len(nn) if nn else 0.0
        weights[aid] = [(bid, w) for _, bid in nn]
    return weights


def benjamini_hochberg(pvals, alpha=0.05):
    """Benjamini-Hochberg FDR. pvals: list of (key, p). Returns the set of keys significant at FDR<=alpha."""
    items = sorted(pvals, key=lambda t: t[1])
    m = len(items)
    if m == 0:
        return set()
    # largest rank k with p_(k) <= (k/m)*alpha; all ranks <= k are significant (step-up)
    cutoff_rank = 0
    for rank, (_, p) in enumerate(items, start=1):
        if p <= (rank / m) * alpha:
            cutoff_rank = rank
    return {items[i][0] for i in range(cutoff_rank)}


def rank_normal(values):
    """Rank-based inverse-normal (van der Waerden) scores: Phi^-1(r / (n + 1)), average ranks for ties.

    None / non-finite values stay None. Used before Local Moran's I so a few extreme tracts in a skewed
    indicator (poverty, densities, counts) cannot dominate the permutation null; the scores keep only
    each tract's rank position within the region."""
    from statistics import NormalDist
    idx = [i for i, v in enumerate(values)
           if v is not None and isinstance(v, (int, float)) and math.isfinite(v)]
    out = [None] * len(values)
    n = len(idx)
    if n == 0:
        return out
    order = sorted(idx, key=lambda i: values[i])
    inv = NormalDist().inv_cdf
    pos = 0
    while pos < n:
        end = pos
        while end + 1 < n and values[order[end + 1]] == values[order[pos]]:
            end += 1
        score = inv(((pos + end) / 2 + 1) / (n + 1))
        for j in range(pos, end + 1):
            out[order[j]] = score
        pos = end + 1
    return out


def _draws_without_replacement(rng, n, k, perms):
    """(perms, k) integer indices into range(n), each row drawn WITHOUT replacement.

    For k << n (the tract case: k=8 of ~750) draw with replacement and redraw only the rows that
    collided (rare), which is exact and fast; when k is a large share of n fall back to a full
    per-row shuffle."""
    if k * k > n:
        return np.argsort(rng.random((perms, n)), axis=1)[:, :k]
    idx = rng.integers(0, n, size=(perms, k))
    while True:
        srt = np.sort(idx, axis=1)
        bad = np.flatnonzero((srt[:, 1:] == srt[:, :-1]).any(axis=1))
        if bad.size == 0:
            return idx
        idx[bad] = rng.integers(0, n, size=(bad.size, k))


def local_moran(obs, weights, perms=9999, alpha=0.05, seed=42, transform="rank_normal"):
    """Local Moran's I (LISA) with a conditional-permutation pseudo p-value and Benjamini-Hochberg
    FDR control across all tracts.

    obs: list of (id, value). weights: knn_weights output.
    Returns {id: {quadrant, I, sig}}.

    The conditional permutation holds z_i fixed and draws k_eff neighbour values WITHOUT replacement
    from the *other* tracts' z-scores (excluding i), which is the correct reference distribution
    (Anselin 1995). A two-sided pseudo p-value is then FDR-adjusted (BH) before classifying significance,
    so the ~n simultaneous local tests don't inflate the false-positive count.

    The permutation count sets the p-value floor 1/(perms+1). BH over m tests needs r tracts at the
    floor before any is rejected whenever floor > r*alpha/m; with m ~ 750 and alpha = 0.05, 999
    permutations (floor 0.001) needed >= 15 such tracts, leaving clustered indicators with none
    significant. 9,999 (floor 0.0001) needs only 2.

    transform="rank_normal" (default) runs the test on rank-based normal scores rather than raw
    values: indicators such as poverty rate are strongly right-skewed, and a handful of tracts 7-9 SD
    above the mean widen the permutation null until almost no clustered tract survives FDR. Rank-normal
    scores make the test robust to that skew; quadrants then mean high/low *rank* within the region.
    transform=None tests the raw values."""
    rng = np.random.default_rng(seed)
    ids = [o[0] for o in obs]
    raw = [o[1] for o in obs]
    if transform == "rank_normal":
        raw = rank_normal(raw)
    elif transform is not None:
        raise ValueError(f"unknown LISA transform: {transform!r}")
    z = zscores(raw)
    zby = dict(zip(ids, z))
    valid_ids = [gid for gid in ids if zby[gid] is not None]
    valid_z = np.array([zby[gid] for gid in valid_ids], dtype=float)
    vpos = {gid: i for i, gid in enumerate(valid_ids)}
    stats = {}        # gid -> (Ii, quadrant)
    pvals = []        # (gid, pseudo_p) for tracts with a computable local statistic
    for gid in ids:
        zi = zby[gid]
        nbrs = weights.get(gid, [])
        if zi is None or not nbrs:
            stats[gid] = (0.0, LISA["NS"])
            continue
        lag, wsum = 0.0, 0.0
        for nb_id, w in nbrs:
            zj = zby.get(nb_id)
            if zj is None:
                continue
            lag += w * zj
            wsum += w
        if wsum == 0:
            stats[gid] = (0.0, LISA["NS"])
            continue
        lag /= wsum
        Ii = zi * lag
        if zi >= 0 and lag >= 0:
            quad = LISA["HH"]
        elif zi < 0 and lag < 0:
            quad = LISA["LL"]
        elif zi >= 0 and lag < 0:
            quad = LISA["HL"]
        else:
            quad = LISA["LH"]
        stats[gid] = (Ii, quad)
        others = np.delete(valid_z, vpos[gid])
        k_eff = min(len(nbrs), len(others))
        if k_eff == 0:
            continue
        draws = _draws_without_replacement(rng, len(others), k_eff, perms)
        null_I = np.abs(zi * others[draws].mean(axis=1))
        ge = int(np.count_nonzero(null_I >= abs(Ii)))
        pvals.append((gid, (ge + 1) / (perms + 1)))
    sig_ids = benjamini_hochberg(pvals, alpha)
    result = {}
    for gid in ids:
        Ii, quad = stats[gid]
        is_sig = gid in sig_ids
        result[gid] = {"quadrant": quad if is_sig else LISA["NS"], "I": Ii, "sig": is_sig}
    return result

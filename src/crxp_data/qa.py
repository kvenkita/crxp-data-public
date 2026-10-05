"""Build-time QA gate.

Fails the build (raises QAError) rather than silently publishing corrupt data. Catches the
catastrophic cases — a year that came back mostly empty, a collapse in tract coverage, or values
outside a configured plausible range — not normal ACS sparsity. Thresholds are lenient by design and
overridable per indicator via the optional `qa:` block in its config. Every check writes a JSON
report and a regenerated summary table (`warehouse/qa/`), including failed checks.
"""
from __future__ import annotations
import json
import math
from pathlib import Path


class QAError(RuntimeError):
    def __init__(self, msg: str, report: dict | None = None, problems: list | None = None):
        super().__init__(msg)
        self.report = report or {}
        self.problems = problems or []


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
        raise QAError(f"QA gate failed for {label}: " + "; ".join(problems),
                      report=report, problems=problems)
    return report


def write_report(ind: dict, report: dict, problems: list, *, value_range, checked_on: str,
                 out_dir: Path) -> Path:
    doc = {"id": ind["id"], "slug": ind["slug"], "label": ind.get("label", ind["slug"]),
           "source": ind.get("source", "acs"), "status": "fail" if problems else "pass",
           "checked_on": checked_on, "range": list(value_range) if value_range else None,
           "years": {str(y): r for y, r in sorted(report.items())}, "problems": list(problems)}
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{ind['slug']}.json"
    p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8", newline="\n")
    return p


def render_summary(out_dir: Path, generated_on: str) -> Path:
    docs = sorted((json.loads(p.read_text(encoding="utf-8")) for p in out_dir.glob("*.json")),
                  key=lambda d: d["id"])
    lines = ["# CRXP QA report", "",
             f"Generated {generated_on}. Each indicator's tract table is checked per year for tract "
             f"coverage, the share of missing values, and (where configured) a plausible value range.",
             "", "| ID | Indicator | Source | Years checked | Min coverage | Max null rate | Range | Status |",
             "|---:|---|---|---|---:|---:|---|---|"]
    for d in docs:
        ys = d["years"]
        yrs = f"{min(ys)}–{max(ys)} ({len(ys)})" if ys else "—"
        cov = f"{min(v['coverage'] for v in ys.values()):.1%}" if ys else "—"
        nul = f"{max(v['null_rate'] for v in ys.values()):.1%}" if ys else "—"
        rng = f"[{d['range'][0]}, {d['range'][1]}]" if d.get("range") else "—"
        lines.append(f"| {d['id']} | {d['label']} | {d['source']} | {yrs} | {cov} | {nul} | {rng} "
                     f"| {d['status'].upper()} |")
    fails = [d for d in docs if d["status"] != "pass"]
    lines += ["", f"{len(docs)} indicators checked; {len(fails)} failed."]
    lines += [f"- **{d['slug']}**: " + "; ".join(d["problems"]) for d in fails]
    p = out_dir / "qa_report.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return p


def run_and_record(ind: dict, tidy, expected_geoids, *, out_dir: Path, checked_on: str) -> dict:
    years = sorted({int(y) for y in tidy["year"].unique()})
    vr = ind.get("qa", {}).get("range")
    try:
        rep = check_tidy(tidy, expected_geoids=expected_geoids, years=years, value_range=vr,
                         label=ind["slug"])
    except QAError as e:
        write_report(ind, e.report, e.problems, value_range=vr, checked_on=checked_on, out_dir=out_dir)
        render_summary(out_dir, checked_on)
        raise
    write_report(ind, rep, [], value_range=vr, checked_on=checked_on, out_dir=out_dir)
    render_summary(out_dir, checked_on)
    return rep


def main(argv: list | None = None, out_dir: Path | None = None) -> int:
    """python -m crxp_data.qa --all : re-check every indicator against the committed warehouse."""
    import sys
    import datetime as dt
    from . import config, geo, warehouse
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["--all"]:
        raise SystemExit("usage: python -m crxp_data.qa --all")
    out = out_dir or (warehouse.WAREHOUSE / "qa")
    today = dt.date.today().isoformat()
    allowed = set(geo.load_tract_centroids())
    failed = 0
    for slug in config.list_indicators():
        ind = config.load_indicator(slug)
        tidy = warehouse.read_warehouse(ind["id"])
        if tidy is None or tidy.empty:
            write_report(ind, {}, ["no warehouse rows"], value_range=None, checked_on=today, out_dir=out)
            failed += 1
            print(f"  {slug}: no warehouse rows")
            continue
        try:
            rep = run_and_record(ind, tidy[tidy["geoid"].isin(allowed)], allowed,
                                 out_dir=out, checked_on=today)
            print(f"  {slug}: ok ({len(rep)} years)")
        except QAError as e:
            failed += 1
            print(f"  {slug}: {e}")
    render_summary(out, today)
    print(f"QA: {len(config.list_indicators())} indicators, {failed} failed -> {out / 'qa_report.md'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

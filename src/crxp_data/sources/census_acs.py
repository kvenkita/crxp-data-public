"""Ingest ACS 5-year estimates (value + MOE) at the tract level, as RAW variables.

The calc engine assembles indicators (median/count/proportion/rate, incl. summed
numerators) from these raw variable columns, so this module just fetches the
variables an indicator declares.

Providers (region.acs.provider = auto|api|census_reporter):
  - api: official Census API (multi-vintage; needs CENSUS_API_KEY)
  - census_reporter: keyless, latest release only
"""
from __future__ import annotations
import os
import time
import json
import urllib.request
import requests
import pandas as pd

_JAM_MIN = -100_000_000
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"}


def _num(x):
    if x is None:
        return float("nan")
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return float("nan") if v <= _JAM_MIN else v


def acs_var_ids(indicator: dict) -> list[str]:
    """All ACS variable ids an indicator references (singular + list roles)."""
    acs = indicator["acs"]
    ids = set()
    for k in ("estimate_var", "moe_var", "den_var", "den_moe_var"):
        if acs.get(k):
            ids.add(acs[k])
    for k in ("num_vars", "num_moe_vars", "den_vars", "den_moe_vars"):
        for v in acs.get(k, []) or []:
            ids.add(v)
    for k in ("num_vars_by_year", "num_moe_vars_by_year"):  # per-vintage numerator overrides
        for vs in (acs.get(k) or {}).values():
            for v in vs or []:
                ids.add(v)
    return sorted(ids)


def _parse_var(v: str):
    """'B19013_001E' -> (table='B19013', col='B19013001', kind='estimate'|'error')."""
    table, rest = v.split("_", 1)
    return table, table + rest[:-1], ("estimate" if v.endswith("E") else "error")


# ---------------- official Census API (keyed) ----------------
def _api_get(url, retries=4):
    """GET a Census API URL with retry/backoff. Returns parsed JSON or raises after `retries`."""
    last = None
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 200 and r.text.lstrip().startswith("["):
                return r.json()
            last = f"HTTP {r.status_code}: {r.text[:140]}"
        except Exception as e:  # noqa: BLE001
            last = str(e)
        time.sleep(1.5 * (attempt + 1))  # linear backoff: 1.5s, 3s, 4.5s
    raise RuntimeError(last or "request failed")


def _fetch_api(region, var_ids, years):
    api_base = region["acs"]["api_base"]
    api_key = os.environ.get("CENSUS_API_KEY")
    if not api_key:
        raise RuntimeError("provider 'api' requires CENSUS_API_KEY in the environment.")
    get = ",".join(["NAME", *var_ids])
    # Subject tables (S####) live at a different API path than detailed tables (B/C####).
    seg = "acs/acs5/subject" if any(v.startswith("S") for v in var_ids) else "acs/acs5"
    counties = region["counties"]
    frames = []
    for y in years:
        rows = []
        year_failures = []  # (county_fips, error) after retries
        for c in counties:
            state, county = c["fips"][:2], c["fips"][2:]
            url = (f"{api_base}/{y}/{seg}?get={get}&for=tract:*"
                   f"&in=state:{state}%20county:{county}&key={api_key}")
            try:
                data = _api_get(url)
            except Exception as e:  # noqa: BLE001
                year_failures.append((c["fips"], str(e)[:120]))
                continue
            idx = {h: i for i, h in enumerate(data[0])}
            for row in data[1:]:
                geoid = row[idx["state"]] + row[idx["county"]] + row[idx["tract"]]
                rec = {"geoid": geoid, "year": y}
                for v in var_ids:
                    rec[v] = _num(row[idx[v]])
                rows.append(rec)
            time.sleep(0.05)
        if year_failures:
            # ALL counties failing identically => the table/vintage doesn't exist for this year:
            # skip the whole year (expected for older vintages of newer tables).
            # A PARTIAL failure (some counties returned data, others didn't) would publish a
            # truncated year and silently corrupt the series -> fail loudly instead.
            if len(year_failures) == len(counties):
                print(f"      ! skipping {y}: table unavailable ({year_failures[0][1]})")
                continue
            raise RuntimeError(
                f"ACS {y}: {len(year_failures)}/{len(counties)} counties failed after retries; "
                f"refusing to publish a partial year (would corrupt the series). "
                f"First failure: {year_failures[0]}")
        frames.append(pd.DataFrame(rows))
    if not frames:
        raise RuntimeError("No ACS years could be fetched (check table availability/vintages).")
    return pd.concat(frames, ignore_index=True)


# ---------------- Census Reporter (keyless, latest only) ----------------
def _cr_get(url, retries=3):
    last = None
    for _ in range(retries):
        try:
            return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=90).read())
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2)
    raise RuntimeError(f"Census Reporter fetch failed: {url}\n{last}")


def _fetch_cr(region, var_ids, years):
    parsed = {v: _parse_var(v) for v in var_ids}
    tables = sorted({t for t, _, _ in parsed.values()})
    geo_ids = ",".join(f"140|05000US{c['fips']}" for c in region["counties"])
    url = (f"https://api.censusreporter.org/1.0/data/show/latest"
           f"?table_ids={','.join(tables)}&geo_ids={geo_ids}")
    resp = _cr_get(url)
    rel = resp.get("release", {}).get("id", "")
    year = int(rel[3:7]) if rel[3:7].isdigit() else max(years)
    print(f"      Census Reporter latest = {rel or '?'} -> year {year} (keyless = latest only)")
    rows = []
    for key, rec in resp["data"].items():
        if not key.startswith("14000US"):
            continue
        row = {"geoid": key[len("14000US"):], "year": year}
        for v, (table, col, kind) in parsed.items():
            try:
                row[v] = _num(rec[table][kind].get(col))
            except Exception:  # noqa: BLE001
                row[v] = float("nan")
        rows.append(row)
    return pd.DataFrame(rows)


def resolve_provider(region: dict) -> str:
    provider = os.environ.get("CRXP_ACS_PROVIDER") or region["acs"].get("provider", "auto")
    if provider == "auto":
        provider = "api" if os.environ.get("CENSUS_API_KEY") else "census_reporter"
    return provider


def fetch_indicator(region: dict, indicator: dict, years: list[int]) -> pd.DataFrame:
    var_ids = acs_var_ids(indicator)
    provider = resolve_provider(region)
    return _fetch_api(region, var_ids, years) if provider == "api" else _fetch_cr(region, var_ids, years)


# ---------------- county-level fetch (authoritative county estimates) ----------------
# County boundaries are stable across the 2010/2020 censuses, so county data needs NO
# harmonization. We fetch each region county's published estimate + MOE so the calc engine
# produces the authoritative county value for every kind (incl. medians/indices/counts) —
# rather than (incorrectly) averaging tract values.
def _fetch_api_county(region, var_ids, years):
    api_base = region["acs"]["api_base"]
    api_key = os.environ.get("CENSUS_API_KEY")
    if not api_key:
        raise RuntimeError("provider 'api' requires CENSUS_API_KEY in the environment.")
    get = ",".join(["NAME", *var_ids])
    seg = "acs/acs5/subject" if any(v.startswith("S") for v in var_ids) else "acs/acs5"
    states = sorted({c["fips"][:2] for c in region["counties"]})
    keep = {c["fips"] for c in region["counties"]}
    frames = []
    for y in years:
        rows, state_failures = [], []
        for ss in states:
            url = f"{api_base}/{y}/{seg}?get={get}&for=county:*&in=state:{ss}&key={api_key}"
            try:
                data = _api_get(url)
            except Exception as e:  # noqa: BLE001
                state_failures.append((ss, str(e)[:120]))
                continue
            idx = {h: i for i, h in enumerate(data[0])}
            for row in data[1:]:
                geoid = row[idx["state"]] + row[idx["county"]]
                if geoid not in keep:
                    continue
                rec = {"geoid": geoid, "year": y}
                for v in var_ids:
                    rec[v] = _num(row[idx[v]])
                rows.append(rec)
            time.sleep(0.05)
        if state_failures:
            if len(state_failures) == len(states):  # table absent for this vintage -> skip year
                print(f"      ! county {y}: table unavailable ({state_failures[0][1]})")
                continue
            raise RuntimeError(f"ACS county {y}: {len(state_failures)}/{len(states)} states failed; "
                               f"refusing partial year. First: {state_failures[0]}")
        frames.append(pd.DataFrame(rows))
    if not frames:
        raise RuntimeError("No ACS county years could be fetched.")
    return pd.concat(frames, ignore_index=True)


def _fetch_cr_county(region, var_ids, years):
    parsed = {v: _parse_var(v) for v in var_ids}
    tables = sorted({t for t, _, _ in parsed.values()})
    geo_ids = ",".join(f"05000US{c['fips']}" for c in region["counties"])
    url = (f"https://api.censusreporter.org/1.0/data/show/latest"
           f"?table_ids={','.join(tables)}&geo_ids={geo_ids}")
    resp = _cr_get(url)
    rel = resp.get("release", {}).get("id", "")
    year = int(rel[3:7]) if rel[3:7].isdigit() else max(years)
    rows = []
    for key, rec in resp["data"].items():
        if not key.startswith("05000US"):
            continue
        row = {"geoid": key[len("05000US"):], "year": year}
        for v, (table, col, kind) in parsed.items():
            try:
                row[v] = _num(rec[table][kind].get(col))
            except Exception:  # noqa: BLE001
                row[v] = float("nan")
        rows.append(row)
    return pd.DataFrame(rows)


def fetch_county_raw(region: dict, var_ids: list[str], years: list[int]) -> pd.DataFrame:
    provider = resolve_provider(region)
    return _fetch_api_county(region, var_ids, years) if provider == "api" else _fetch_cr_county(region, var_ids, years)


def fetch_indicator_county(region: dict, indicator: dict, years: list[int]) -> pd.DataFrame:
    return fetch_county_raw(region, acs_var_ids(indicator), years)


def county_population(region: dict, years: list[int]) -> dict:
    """{(county_geoid, year): total population} — used to population-weight region medians/indices."""
    df = fetch_county_raw(region, ["B01003_001E"], years)
    return {(row["geoid"], int(row["year"])): row["B01003_001E"] for _, row in df.iterrows()}

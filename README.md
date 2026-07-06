# crxp-data — Carolinas Regional Explorer data pipeline

Open-source, reproducible pipeline that turns public data into reviewed, **tract-level**
indicators (with margins of error) and hands them to the CRXP app. No ArcGIS required.

Stages: **ingest → normalize → harmonize geography → estimate-to-tract → indicator calc (MOE)
→ spatial (z / Moran's I / LISA) → review → export** (app data contract + parquet/DuckDB warehouse).
This is the engine behind the CRXP app's `crxp/static/data` contract. See `docs/` for the methodology guide, pipeline documentation, and working paper.

## Setup
```bash
cd crxp-data
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS/Linux
```

## Configuration (no code needed to add an indicator)
- `config/region.yml` — the 14 counties, ACS settings, reliability thresholds.
- `config/sources/<id>.yml` — a raw source (provider, geo level, cadence, license, **update_status /
  last_release / decommission_risk**).
- `config/indicators/<slug>.yml` — an indicator (source, ACS table/vars, `kind`, format, theme, metadata).

## Run
```bash
# Windows PowerShell
$env:PYTHONPATH="src"; .venv\Scripts\python -m crxp_data.build household-income
# add --handoff to also copy the contract into ../crxp/static/data
$env:PYTHONPATH="src"; .venv\Scripts\python -m crxp_data.build household-income --handoff
```

### ACS providers (important)
`region.acs.provider`:
- **`census_reporter`** (default, **keyless**) — convenient, but serves only the **latest** 5-year
  release (one year). Good for a quick refresh / demo.
- **`api`** (official Census API) — required for **multi-vintage history** and **comparable-period
  change/significance**. Set a free key: `setx CENSUS_API_KEY <key>` (get one at
  https://api.census.gov/data/key_signup.html), then set `provider: api`.

## Outputs
- **Warehouse (shared backend):** `warehouse/tract_indicators/<id>.parquet` + `warehouse/crxp.duckdb`
  (long table `tract_indicators` with value, **moe, cv, reliability**, period, est_method, source vintage).
  Any app (CRXP, QoL, future) can query the DuckDB.
- **App contract:** `exports/crxp/data/{values,analytics/z,analytics/lisa}/<id>.json` — same shape the
  app reads, **plus** per-tract `moe`/`cv`/`reliability`. `--handoff` copies it into `../crxp/static/data`.

## Margins of error & ACS comparability
- Every estimate carries a 90% MOE; the calc engine propagates MOE through derived rates and computes
  CV + a reliability flag (ok / caution / unreliable). See `src/crxp_data/indicators/calc.py`.
- ACS 5-year vintages **overlap** (adjacent years share 4 years of sample), so the annual series is
  **rolling**; "change" and significance are valid only between **non-overlapping** periods
  (`region.acs.comparable_years`). The app labels series accordingly (uncertainty UI — P2.1b).

## Add a new indicator (SOP)
1. Add `config/indicators/<slug>.yml` (and a `config/sources/<id>.yml` if a new source).
2. Implement/confirm a source ingester in `src/crxp_data/sources/`.
3. `python -m crxp_data.build <slug>` → review the printed summary + `warehouse`.
4. When satisfied, re-run with `--handoff`; then `cd ../crxp && npm run build` and review in the app.

## Tests
```bash
$env:PYTHONPATH="src"; .venv\Scripts\python -m pytest -q
```

## Source sustainability
Some sources are static/discontinued (Eviction Lab tract, USDA Food Access, HUD LAI, USALEEP). Each
source YAML records `update_status` + `decommission_risk`; the app shows each indicator's vintage. See
`catalog/registry.md`.

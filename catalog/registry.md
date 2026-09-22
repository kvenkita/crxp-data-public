# Source registry / catalog (catalog-in-place)

Large raw files stay where they are (Dropbox); this catalog records what exists, where, vintage,
license, cadence, and **sustainability**. Machine-readable specs live in `config/sources/*.yml`.

| Source | Theme(s) | Native geo | Latest | Cadence | Update status | Decommission risk | Location |
|---|---|---|---|---|---|---|---|
| ACS 5-year (Census API / Census Reporter) | all | tract | 2024 | annual (rolling 5-yr) | active | low | Census API (`provider: api` + key) / Census Reporter (latest only) |
| CDC PLACES | health | tract | 2025 | annual | active | low | `.../Charlotte Regional Explorer/Data/3) CDC Places` + CDC API |
| CDC/ATSDR SVI | health/social | tract | 2022 | biennial | active | low | `.../Data/10) CDC Social Vulnerability Index (SVI)` |
| FCC Broadband (BDC) | connectivity | block/location | 2025 | semiannual | active | low | `.../Data/5) FCC Broadband Data` |
| Opportunity Atlas | economy/mobility | tract | fixed cohorts (+2025 modules) | event-driven | enrichment | low | `.../Data/9) Opportunity Atlas` |
| Eviction Lab | housing | tract | 2018 (national) | static | **keep-but-watch** | medium | `.../Data/12) Eviction Lab` |
| USDA Food Access Atlas | health/food | tract | 2019 | static | **keep-but-watch** | medium-high | `.../Data/6) USDA Food Access Research Atlas` |
| HUD Location Affordability Index | housing/transport | tract/BG | 2019 (v3) | static | **deprecate** | high | `.../Data/7) HUD Location Affordability Index` |
| USALEEP life expectancy | health | tract | 2010–2015 | static (one-time) | **keep as benchmark** | high | `.../Data/8) USALEEP` |
| EPA air quality (AQS) | environment | monitor point | 2025 | annual | active | low | `.../Data/4) Environmental Protection Agency (EPA)` |
| NC parcels | (proximity input) | parcel | — | as released | active | low | `.../Data/NC_Parcels_all.gdb` |
| Mecklenburg tax parcels | (proximity input) | parcel | 2025 | annual | active | low | QoL `.../Data/Raw/Shared-Data/2025/TaxData_2025.gpkg` |
| LEHD LODES8 WAC (workplace jobs) | economy | block (2020) | 2022 | annual | active | low | Census LEHD `https://lehd.ces.census.gov/data/lodes/LODES8/` |

**Gaps to resolve:** SC parcels (York/Chester/Lancaster) for proximity; geography crosswalks (pre-2020
ACS vintages → 2020 tracts). **Replacement plan:** food access → Tier-4 grocery proximity; eviction →
court records / Eviction Tracking System.

Full cited research: session tool-results (`toolu_011Gmqq3wp8rTFYoBozQSN66.json`).

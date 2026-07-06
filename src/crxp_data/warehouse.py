"""Processed-data warehouse: parquet per indicator + a DuckDB table (shared backend)."""
from __future__ import annotations
from pathlib import Path
import duckdb
from .config import ROOT

WAREHOUSE = ROOT / "warehouse"
COLUMNS = [
    "geoid", "indicator_id", "year", "value", "moe", "cv", "reliability",
    "period_start", "period_end", "is_rolling", "est_method",
    "source_id", "source_vintage", "redacted", "created",
]


def read_warehouse(indicator_id: int):
    """Read one indicator's stored rows (geoid, year, value, moe, cv, reliability) from parquet."""
    import pandas as pd
    pq = WAREHOUSE / "tract_indicators" / f"{indicator_id}.parquet"
    if not pq.exists():
        return None
    df = pd.read_parquet(pq)
    return df[["geoid", "year", "value", "moe", "cv", "reliability"]].copy()


# ---- county + region rollup (authoritative county estimates; geoid 'REGION' = pooled region) ----
def read_county_warehouse(indicator_id: int):
    import pandas as pd
    pq = WAREHOUSE / "county_indicators" / f"{indicator_id}.parquet"
    if not pq.exists():
        return None
    return pd.read_parquet(pq)[["geoid", "year", "value", "moe", "cv", "reliability"]].copy()


def write_county_warehouse(df, indicator_id: int):
    (WAREHOUSE / "county_indicators").mkdir(parents=True, exist_ok=True)
    cols = ["geoid", "year", "value", "moe", "cv", "reliability"]
    out = df[cols].copy()
    out.insert(1, "indicator_id", indicator_id)
    pq = WAREHOUSE / "county_indicators" / f"{indicator_id}.parquet"
    out.to_parquet(pq, index=False)
    return pq, len(out)


def write_warehouse(df, indicator_id: int):
    """Write/replace one indicator's rows in parquet + crxp.duckdb tract_indicators."""
    WAREHOUSE.mkdir(parents=True, exist_ok=True)
    (WAREHOUSE / "tract_indicators").mkdir(exist_ok=True)
    df = df[COLUMNS].copy()
    pq = WAREHOUSE / "tract_indicators" / f"{indicator_id}.parquet"
    df.to_parquet(pq, index=False)

    con = duckdb.connect(str(WAREHOUSE / "crxp.duckdb"))
    con.execute(
        """CREATE TABLE IF NOT EXISTS tract_indicators (
            geoid VARCHAR, indicator_id INTEGER, year INTEGER, value DOUBLE, moe DOUBLE,
            cv DOUBLE, reliability VARCHAR, period_start INTEGER, period_end INTEGER,
            is_rolling BOOLEAN, est_method VARCHAR, source_id VARCHAR, source_vintage VARCHAR,
            redacted BOOLEAN, created VARCHAR)"""
    )
    con.execute("DELETE FROM tract_indicators WHERE indicator_id = ?", [indicator_id])
    con.register("incoming", df)
    con.execute("INSERT INTO tract_indicators SELECT * FROM incoming")
    n = con.execute("SELECT count(*) FROM tract_indicators WHERE indicator_id = ?", [indicator_id]).fetchone()[0]
    con.close()
    return pq, n

"""crxp-data: open-source data pipeline for the Carolinas Regional Explorer.

Stages: ingest -> normalize -> harmonize geography -> estimate-to-tract ->
indicator calc (MOE) -> spatial (z / Moran's I / LISA) -> review -> export
(app data contract + parquet/duckdb warehouse).
"""
__version__ = "0.1.0"

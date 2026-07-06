"""Load region + indicator + source configuration (YAML)."""
from __future__ import annotations
from pathlib import Path
import yaml

# project root = .../crxp-data (two levels up from this file: src/crxp_data/config.py)
ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config"


# Always read config as UTF-8 — Path.read_text() defaults to the locale encoding (cp1252 on Windows),
# which mangles characters like "≥" or "–" into mojibake in the generated contract.
def load_region() -> dict:
    return yaml.safe_load((CONFIG / "region.yml").read_text(encoding="utf-8"))


def load_indicator(slug: str) -> dict:
    return yaml.safe_load((CONFIG / "indicators" / f"{slug}.yml").read_text(encoding="utf-8"))


def load_source(source_id: str) -> dict:
    return yaml.safe_load((CONFIG / "sources" / f"{source_id}.yml").read_text(encoding="utf-8"))


def list_indicators() -> list[str]:
    return sorted(p.stem for p in (CONFIG / "indicators").glob("*.yml"))

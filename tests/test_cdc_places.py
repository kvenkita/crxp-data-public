import pandas as pd
from crxp_data.sources import cdc_places


def test_fetch_measure_tags_vintage_from_winning_release(monkeypatch):
    def fake_query(ds, where):
        return [{"locationid": "37119000100", "year": 2023, "data_value": "10",
                 "low_confidence_limit": "9", "high_confidence_limit": "11",
                 "totalpopulation": "100"}]
    monkeypatch.setattr(cdc_places, "_query", fake_query)
    region = {"counties": [{"fips": "37119"}]}
    # all releases return the same (geoid, 2023); newest (2025, vintage 2020) wins
    out = cdc_places.fetch_measure(region, "OBESITY", "Crude prevalence", "tract")
    assert "vintage" in out.columns
    assert int(out.iloc[0]["vintage"]) == 2020
    # restrict to the 2020 release only -> vintage 2010
    out10 = cdc_places.fetch_measure(region, "OBESITY", "Crude prevalence", "tract",
                                     releases=[cdc_places.RELEASES[0]])
    assert int(out10.iloc[0]["vintage"]) == 2010


def test_newest_wins_keeps_latest_release_per_geoid_year():
    df = pd.DataFrame([
        {"geoid": "37119000100", "year": 2022, "value": 10.0, "moe": 1.0, "pop": 100, "release": 2024, "vintage": 2020},
        {"geoid": "37119000100", "year": 2022, "value": 11.5, "moe": 1.2, "pop": 105, "release": 2025, "vintage": 2020},
        {"geoid": "37119000100", "year": 2021, "value": 9.0, "moe": 0.9, "pop": 99, "release": 2024, "vintage": 2020},
        {"geoid": "37119000100", "year": 2020, "value": 8.0, "moe": 0.8, "pop": 98, "release": 2023, "vintage": 2010},
    ])
    out = cdc_places.newest_wins(df).sort_values("year").reset_index(drop=True)
    assert "release" not in out.columns
    # 2022 -> newer 2025 release value; 2021 -> only the 2024 release
    assert out.loc[out.year == 2022, "value"].iloc[0] == 11.5
    assert out.loc[out.year == 2021, "value"].iloc[0] == 9.0
    assert len(out) == 3
    # vintage is preserved from the winning release row
    assert int(out.loc[out.year == 2022, "vintage"].iloc[0]) == 2020
    assert int(out.loc[out.year == 2020, "vintage"].iloc[0]) == 2010


def test_registry_has_six_releases_with_required_keys():
    assert len(cdc_places.RELEASES) == 6
    for r in cdc_places.RELEASES:
        assert set(r) >= {"year", "tract", "county", "vintage", "data_years"}


def test_fetch_measure_routes_by_level_tags_release_and_dedupes(monkeypatch):
    calls = []

    def fake_query(ds, where):
        calls.append(where)
        return [{"locationid": "37119000100", "year": 2023, "data_value": "10",
                 "low_confidence_limit": "9", "high_confidence_limit": "11",
                 "totalpopulation": "100"}]

    monkeypatch.setattr(cdc_places, "_query", fake_query)
    region = {"counties": [{"fips": "37119"}]}

    out_c = cdc_places.fetch_measure(region, "OBESITY", "Crude prevalence", "county")
    assert all("locationid in" in w for w in calls)
    assert all("countyfips" not in w for w in calls)
    # county fetch skips releases whose county dataset is None (e.g. 2020 name-keyed)
    expected_county_calls = sum(1 for r in cdc_places.RELEASES if r["county"])
    assert len(calls) == expected_county_calls
    # all queried releases return the same (geoid, year) -> newest_wins collapses to one row
    assert len(out_c) == 1 and out_c.iloc[0]["geoid"] == "37119000100"

    calls.clear()
    cdc_places.fetch_measure(region, "OBESITY", "Crude prevalence", "tract")
    assert all("countyfips in" in w for w in calls)

from __future__ import annotations

import csv
import json
import sqlite3
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from strava_sync.exceptions import StorageError
from strava_sync.storage import ActivityStore


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ActivityStore]:
    with ActivityStore(tmp_path / "data" / "strava.db") as activity_store:
        yield activity_store


def _row(store: ActivityStore, activity_id: int, columns: str) -> tuple[Any, ...]:
    row = store._conn.execute(
        f"SELECT {columns} FROM activities WHERE id = ?", (activity_id,)
    ).fetchone()
    assert row is not None
    return tuple(row)


def test_empty_store(store: ActivityStore) -> None:
    assert store.count() == 0
    assert store.latest_start_time() is None
    assert store.upsert_many([]) == 0
    assert store.ids_missing_gpx() == []


def test_maps_training_log_fields(
    store: ActivityStore, activity_factory: Callable[..., dict[str, Any]]
) -> None:
    store.upsert_many([activity_factory(7, commute=True, athlete_gear_id=99)])

    assert _row(
        store,
        7,
        "sport_type, start_time_utc, start_time_local, distance_m, moving_time_s, "
        "elevation_gain_m, relative_effort, commute, gear_id, has_gps",
    ) == ("Run", "2026-09-27T09:17:52Z", "2026-09-27T11:17:52", 10000.0, 3000, 83.2, 42, 1, 99, 1)


def test_upsert_updates_and_keeps_raw_json(
    store: ActivityStore, activity_factory: Callable[..., dict[str, Any]]
) -> None:
    store.upsert_many([activity_factory(1), activity_factory(2)])
    store.upsert_many([activity_factory(1, name="Renamed")])

    name, raw = _row(store, 1, "name, raw_json")
    assert store.count() == 2
    assert name == "Renamed"
    assert json.loads(raw)["name"] == "Renamed"


def test_upsert_keeps_downloaded_gpx(
    store: ActivityStore, activity_factory: Callable[..., dict[str, Any]]
) -> None:
    store.upsert_many([activity_factory(1)])
    store.set_gpx_file(1, "data/gpx/1.gpx")
    store.upsert_many([activity_factory(1, name="Edited")])

    assert _row(store, 1, "gpx_file") == ("data/gpx/1.gpx",)


def test_falls_back_to_display_type(
    store: ActivityStore, activity_factory: Callable[..., dict[str, Any]]
) -> None:
    store.upsert_many([activity_factory(1, sport_type=None, display_type="Hike")])

    assert _row(store, 1, "sport_type") == ("Hike",)


def test_activity_without_numeric_id_is_rejected(store: ActivityStore) -> None:
    with pytest.raises(StorageError):
        store.upsert_many([{"id": "1"}])


def test_latest_start_time(
    store: ActivityStore, activity_factory: Callable[..., dict[str, Any]]
) -> None:
    store.upsert_many(
        [
            activity_factory(1, start_time="2026-01-01T10:00:00+0000"),
            activity_factory(2, start_time="2026-03-05T07:30:00+0000"),
        ]
    )

    assert store.latest_start_time() == datetime(2026, 3, 5, 7, 30, tzinfo=timezone.utc)


def test_ids_missing_gpx_only_lists_gps_activities(
    store: ActivityStore, activity_factory: Callable[..., dict[str, Any]]
) -> None:
    store.upsert_many(
        [
            activity_factory(1, start_time="2026-01-01T10:00:00+0000"),
            activity_factory(2, start_time="2026-02-01T10:00:00+0000"),
            activity_factory(3, has_latlng=False),
        ]
    )
    store.set_gpx_file(1, "x.gpx")

    assert store.ids_missing_gpx() == [2]


def test_export_csv(
    store: ActivityStore, tmp_path: Path, activity_factory: Callable[..., dict[str, Any]]
) -> None:
    store.upsert_many(
        [
            activity_factory(2, start_time="2026-02-01T10:00:00+0000"),
            activity_factory(
                1,
                start_time="2026-01-01T10:00:00+0000",
                sport_type="WeightTraining",
                distance_raw=0.0,
            ),
        ]
    )
    path = tmp_path / "out" / "activities.csv"

    count = store.export_csv(path, delimiter=";", encoding="utf-8-sig")

    assert count == 2
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter=";"))
    assert [row["id"] for row in rows] == ["1", "2"]
    run = rows[1]
    assert run["distance_km"] == "10.00"
    assert run["moving_time"] == "0:50:00"
    assert run["pace_min_per_km"] == "5:00"
    assert run["speed_kmh"] == "12.0"
    assert run["commute"] == "0"
    assert rows[0]["pace_min_per_km"] == ""
    assert rows[0]["distance_km"] == ""


def test_rejects_newer_schema(tmp_path: Path) -> None:
    path = tmp_path / "strava.db"
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()

    with pytest.raises(StorageError, match="newer than supported"):
        ActivityStore(path)


def test_reopening_keeps_data(
    tmp_path: Path, activity_factory: Callable[..., dict[str, Any]]
) -> None:
    path = tmp_path / "strava.db"
    with ActivityStore(path) as first:
        first.upsert_many([activity_factory(1)])

    with ActivityStore(path) as second:
        assert second.count() == 1

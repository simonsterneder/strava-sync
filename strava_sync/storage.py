"""SQLite persistence and CSV export of activities."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from .activity import format_utc, start_time_local, start_time_utc
from .exceptions import StorageError

SCHEMA_VERSION = 1


def _raw(key: str) -> Callable[[dict[str, Any]], Any]:
    return lambda activity: activity.get(key)


def _utc(activity: dict[str, Any]) -> str | None:
    start = start_time_utc(activity)
    return format_utc(start) if start else None


def _local(activity: dict[str, Any]) -> str | None:
    start = start_time_local(activity)
    return start.isoformat() if start else None


# (column, SQLite type, extractor from the training-log payload)
_FIELDS: tuple[tuple[str, str, Callable[[dict[str, Any]], Any]], ...] = (
    ("id", "INTEGER PRIMARY KEY", _raw("id")),
    ("name", "TEXT", _raw("name")),
    ("sport_type", "TEXT", lambda a: a.get("sport_type") or a.get("display_type")),
    ("start_time_utc", "TEXT", _utc),
    ("start_time_local", "TEXT", _local),
    ("distance_m", "REAL", _raw("distance_raw")),
    ("moving_time_s", "INTEGER", _raw("moving_time_raw")),
    ("elapsed_time_s", "INTEGER", _raw("elapsed_time_raw")),
    ("elevation_gain_m", "REAL", _raw("elevation_gain_raw")),
    ("relative_effort", "INTEGER", _raw("suffer_score")),
    ("commute", "INTEGER", _raw("commute")),
    ("trainer", "INTEGER", _raw("trainer")),
    ("private", "INTEGER", _raw("private")),
    ("visibility", "TEXT", _raw("visibility")),
    ("gear_id", "INTEGER", _raw("athlete_gear_id")),
    ("bike_id", "INTEGER", _raw("bike_id")),
    ("has_gps", "INTEGER", _raw("has_latlng")),
    ("description", "TEXT", _raw("description")),
    ("url", "TEXT", _raw("activity_url")),
)
_COLUMNS = tuple(column for column, _, _ in _FIELDS)
_CSV_COLUMNS = (*_COLUMNS, "gpx_file")
_DERIVED_CSV_COLUMNS = ("distance_km", "moving_time", "pace_min_per_km", "speed_kmh")


class ActivityStore:
    """Activities keyed by Strava id. The raw payload is kept as JSON so no data is lost."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(path)
        except sqlite3.Error as exc:
            raise StorageError(f"Cannot open database {path}: {exc}") from exc
        try:
            self._migrate()
        except BaseException as exc:
            self._conn.close()
            if isinstance(exc, sqlite3.DatabaseError):
                raise StorageError(f"Cannot open database {path}: {exc}") from exc
            raise

    def __enter__(self) -> ActivityStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def _migrate(self) -> None:
        (version,) = self._conn.execute("PRAGMA user_version").fetchone()
        if version > SCHEMA_VERSION:
            raise StorageError(
                f"Database schema version {version} is newer than supported ({SCHEMA_VERSION}). "
                "Please update strava-sync."
            )
        if version < 1:
            columns = ",\n    ".join(f"{name} {sql_type}" for name, sql_type, _ in _FIELDS)
            with self._conn:
                self._conn.execute(
                    f"CREATE TABLE IF NOT EXISTS activities (\n    {columns},\n"
                    "    gpx_file TEXT,\n"
                    "    raw_json TEXT NOT NULL,\n"
                    "    synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP\n)"
                )
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_activities_start ON activities (start_time_utc)"
                )
                self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def upsert_many(self, activities: Iterable[dict[str, Any]]) -> int:
        """Insert or update activities in one transaction; returns the number written."""
        rows = [_to_row(activity) for activity in activities]
        if not rows:
            return 0
        columns = (*_COLUMNS, "raw_json")
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{column} = excluded.{column}" for column in columns[1:])
        with self._conn:
            self._conn.executemany(
                f"INSERT INTO activities ({', '.join(columns)}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}, synced_at = CURRENT_TIMESTAMP",
                rows,
            )
        return len(rows)

    def latest_start_time(self) -> datetime | None:
        (value,) = self._conn.execute("SELECT MAX(start_time_utc) FROM activities").fetchone()
        return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None

    def count(self) -> int:
        (count,) = self._conn.execute("SELECT COUNT(*) FROM activities").fetchone()
        return int(count)

    def ids_missing_gpx(self) -> list[int]:
        rows = self._conn.execute(
            "SELECT id FROM activities WHERE has_gps = 1 AND gpx_file IS NULL "
            "ORDER BY start_time_utc DESC"
        )
        return [int(activity_id) for (activity_id,) in rows]

    def set_gpx_file(self, activity_id: int, path: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE activities SET gpx_file = ? WHERE id = ?", (path, activity_id)
            )

    def export_csv(self, path: Path, *, delimiter: str = ";", encoding: str = "utf-8-sig") -> int:
        """Write all activities (oldest first) to ``path``; returns the number of rows."""
        cursor = self._conn.execute(
            f"SELECT {', '.join(_CSV_COLUMNS)} FROM activities ORDER BY start_time_utc"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with path.open("w", newline="", encoding=encoding) as fh:
            writer = csv.writer(fh, delimiter=delimiter)
            writer.writerow((*_CSV_COLUMNS, *_DERIVED_CSV_COLUMNS))
            for row in cursor:
                record = dict(zip(_CSV_COLUMNS, row, strict=True))
                writer.writerow((*row, *_derived_values(record)))
                count += 1
        return count


def _to_row(activity: dict[str, Any]) -> tuple[Any, ...]:
    if not isinstance(activity.get("id"), int):
        raise StorageError("Received an activity without a numeric 'id' from Strava.")
    values: list[Any] = []
    for _, _, extract in _FIELDS:
        value = extract(activity)
        values.append(int(value) if isinstance(value, bool) else value)
    values.append(json.dumps(activity, ensure_ascii=False, separators=(",", ":")))
    return tuple(values)


def _derived_values(record: dict[str, Any]) -> tuple[str, str, str, str]:
    distance = record["distance_m"]
    moving_time = record["moving_time_s"]
    has_speed = bool(distance and moving_time)
    return (
        f"{distance / 1000:.2f}" if distance else "",
        _format_duration(moving_time) if moving_time else "",
        _format_pace(moving_time / (distance / 1000)) if has_speed else "",
        f"{distance / moving_time * 3.6:.1f}" if has_speed else "",
    )


def _format_duration(seconds: int) -> str:
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def _format_pace(seconds_per_km: float) -> str:
    minutes, seconds = divmod(round(seconds_per_km), 60)
    return f"{minutes}:{seconds:02d}"

"""Helpers to interpret activity records from Strava's training log endpoint."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def start_time_utc(activity: dict[str, Any]) -> datetime | None:
    """Start time as an aware UTC datetime (``start_time`` looks like 2026-09-27T09:17:52+0000)."""
    value = activity.get("start_time")
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc)
    except ValueError:
        return None


def start_time_local(activity: dict[str, Any]) -> datetime | None:
    """Wall-clock start time at the activity's location (naive datetime).

    Strava encodes it as a Unix timestamp of the local time interpreted as UTC.
    """
    value = activity.get("start_date_local_raw")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

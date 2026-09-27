from __future__ import annotations

from datetime import datetime, timezone

import pytest

from strava_sync.activity import format_utc, start_time_local, start_time_utc

from .conftest import make_activity


def test_start_time_utc_from_training_log_format() -> None:
    assert start_time_utc(make_activity(1)) == datetime(2026, 9, 27, 9, 17, 52, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-09-27T11:17:52+0200", datetime(2026, 9, 27, 9, 17, 52, tzinfo=timezone.utc)),
        ("2026-09-27T09:17:52Z", datetime(2026, 9, 27, 9, 17, 52, tzinfo=timezone.utc)),
        ("2026-09-27T09:17:52", None),  # no timezone: refuse to guess
        ("garbage", None),
        (None, None),
    ],
)
def test_start_time_utc_variants(value: object, expected: datetime | None) -> None:
    assert start_time_utc({"start_time": value}) == expected


def test_start_time_local_is_wall_clock_time() -> None:
    assert start_time_local(make_activity(1)) == datetime(2026, 9, 27, 11, 17, 52)
    assert start_time_local({"start_date_local_raw": None}) is None
    assert start_time_local({"start_date_local_raw": True}) is None


def test_format_utc() -> None:
    value = datetime(2026, 9, 27, 11, 17, 52, tzinfo=timezone.utc)

    assert format_utc(value) == "2026-09-27T11:17:52Z"

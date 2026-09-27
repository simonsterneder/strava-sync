from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

# Values from a real training-log record: 09:17:52 UTC, local wall-clock time 11:17:52.
START_TIME = "2026-09-27T09:17:52+0000"
START_LOCAL_RAW = 1790507872  # decodes to 11:17:52 (CEST)


def make_activity(activity_id: int, **overrides: Any) -> dict[str, Any]:
    """An activity record shaped like /athlete/training_activities returns it."""
    activity: dict[str, Any] = {
        "id": activity_id,
        "name": f"Run {activity_id}",
        "sport_type": "Run",
        "display_type": "Run",
        "start_time": START_TIME,
        "start_date_local_raw": START_LOCAL_RAW,
        "distance": "10.00",
        "distance_raw": 10000.0,
        "moving_time": "50:00",
        "moving_time_raw": 3000,
        "elapsed_time_raw": 3100,
        "elevation_gain_raw": 83.2,
        "suffer_score": 42,
        "commute": False,
        "trainer": False,
        "private": False,
        "visibility": "everyone",
        "athlete_gear_id": None,
        "bike_id": None,
        "has_latlng": True,
        "description": "",
        "activity_url": f"https://www.strava.com/activities/{activity_id}",
    }
    activity.update(overrides)
    return activity


def training_page(models: list[dict[str, Any]], total: int, page: int = 1) -> dict[str, Any]:
    return {"models": models, "page": page, "perPage": 20, "total": total}


@dataclass
class FakeHttp:
    """Stand-in for WebSession. Queued items are returned, or raised if they are exceptions."""

    responses: list[Any] = field(default_factory=list)
    calls: list[tuple[str, dict[str, Any] | None]] = field(default_factory=list)

    def _next(self, path: str, params: Mapping[str, Any] | None) -> Any:
        self.calls.append((path, dict(params) if params else None))
        if not self.responses:
            raise AssertionError(f"Unexpected request to {path}")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return self._next(path, params)

    def get_bytes(self, path: str) -> bytes:
        result = self._next(path, None)
        assert isinstance(result, bytes)
        return result


@pytest.fixture
def activity_factory() -> Callable[..., dict[str, Any]]:
    return make_activity


@pytest.fixture
def fake_http() -> FakeHttp:
    return FakeHttp()

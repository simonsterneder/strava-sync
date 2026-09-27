from __future__ import annotations

from datetime import datetime, timezone

import pytest

from strava_sync.client import THROTTLE_BACKOFF_SECONDS, StravaWebClient
from strava_sync.exceptions import (
    ApiError,
    RateLimitError,
    SessionExpiredError,
    ThrottledError,
)

from .conftest import FakeHttp, make_activity, training_page


def _client(http: FakeHttp, delay: float = 0.0) -> tuple[StravaWebClient, list[float]]:
    sleeps: list[float] = []
    clock = iter(float(i) for i in range(1000))
    client = StravaWebClient(
        http, request_delay=delay, sleep=sleeps.append, clock=lambda: next(clock)
    )
    return client, sleeps


def test_current_athlete_id(fake_http: FakeHttp) -> None:
    fake_http.responses.append({"currentAthlete": {"id": 50392655}, "pageContext": {}})
    client, _ = _client(fake_http)

    assert client.current_athlete_id() == 50392655
    assert fake_http.calls == [("/frontend/athletes/current", None)]


def test_current_athlete_missing_means_logged_out(fake_http: FakeHttp) -> None:
    fake_http.responses.append({"currentAthlete": None})
    client, _ = _client(fake_http)

    with pytest.raises(SessionExpiredError):
        client.current_athlete_id()


def test_pages_until_total_is_reached(fake_http: FakeHttp) -> None:
    fake_http.responses += [
        training_page([make_activity(3), make_activity(2)], total=3),
        training_page([make_activity(1)], total=3, page=2),
    ]
    client, _ = _client(fake_http)

    pages = list(client.iter_activity_pages())

    assert [[a["id"] for a in page] for page in pages] == [[3, 2], [1]]
    assert [params for _, params in fake_http.calls] == [{"page": 1}, {"page": 2}]


def test_stops_on_empty_page(fake_http: FakeHttp) -> None:
    fake_http.responses += [
        training_page([make_activity(1)], total=None),  # type: ignore[arg-type]
        training_page([], total=None),  # type: ignore[arg-type]
    ]
    client, _ = _client(fake_http)

    assert len(list(client.iter_activity_pages())) == 1
    assert len(fake_http.calls) == 2


def test_incremental_stops_once_older_activities_are_reached(fake_http: FakeHttp) -> None:
    fake_http.responses += [
        training_page(
            [
                make_activity(3, start_time="2026-09-27T09:00:00+0000"),
                make_activity(2, start_time="2026-09-10T09:00:00+0000"),
            ],
            total=100,
        ),
    ]
    client, _ = _client(fake_http)
    stop_before = datetime(2026, 9, 20, tzinfo=timezone.utc)

    pages = list(client.iter_activity_pages(stop_before=stop_before))

    assert len(pages) == 1
    assert len(fake_http.calls) == 1


def test_unexpected_payload_is_an_error(fake_http: FakeHttp) -> None:
    fake_http.responses.append({"error": "nope"})
    client, _ = _client(fake_http)

    with pytest.raises(ApiError, match="Unexpected response"):
        list(client.iter_activity_pages())


def test_requests_are_paced(fake_http: FakeHttp) -> None:
    fake_http.responses += [
        training_page([make_activity(2)], total=2),
        training_page([make_activity(1)], total=2, page=2),
    ]
    client, sleeps = _client(fake_http, delay=5.0)

    list(client.iter_activity_pages())

    # Fake clock advances by 1 s per reading; the second request waits for the rest.
    assert sleeps == [4.0]


def test_throttling_waits_and_retries(fake_http: FakeHttp) -> None:
    fake_http.responses += [ThrottledError("429"), {"currentAthlete": {"id": 1}}]
    client, sleeps = _client(fake_http)

    assert client.current_athlete_id() == 1
    assert sleeps == [THROTTLE_BACKOFF_SECONDS[0]]


def test_persistent_throttling_gives_up(fake_http: FakeHttp) -> None:
    fake_http.responses += [ThrottledError("429")] * (len(THROTTLE_BACKOFF_SECONDS) + 1)
    client, sleeps = _client(fake_http)

    with pytest.raises(RateLimitError):
        client.current_athlete_id()
    assert sleeps == list(THROTTLE_BACKOFF_SECONDS)


def test_download_gpx(fake_http: FakeHttp) -> None:
    fake_http.responses.append(b'<?xml version="1.0"?><gpx/>')
    client, _ = _client(fake_http)

    assert client.download_gpx(42).startswith(b"<?xml")
    assert fake_http.calls == [("/activities/42/export_gpx", None)]


def test_download_gpx_rejects_non_gpx(fake_http: FakeHttp) -> None:
    fake_http.responses.append(b"<!doctype html><html>login</html>")
    client, _ = _client(fake_http)

    with pytest.raises(ApiError, match="did not return a GPX"):
        client.download_gpx(42)

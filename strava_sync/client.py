"""Client for the JSON endpoints behind strava.com's "My Activities" page.

These are the same requests the website makes in your browser. They are not a public,
documented API, so the client is deliberately defensive about the response shape.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime
from typing import Any, Protocol, TypeVar

from .activity import start_time_utc
from .exceptions import ApiError, RateLimitError, SessionExpiredError, ThrottledError

log = logging.getLogger(__name__)

T = TypeVar("T")

# Waits after consecutive HTTP 429 answers before giving up.
THROTTLE_BACKOFF_SECONDS = (60.0, 300.0, 900.0)


class HttpSession(Protocol):
    def get_json(self, path: str, params: Mapping[str, str | int] | None = None) -> Any: ...

    def get_bytes(self, path: str) -> bytes: ...


class StravaWebClient:
    def __init__(
        self,
        http: HttpSession,
        *,
        request_delay: float,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._request_delay = request_delay
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None

    def current_athlete_id(self) -> int:
        data = self._call(self._http.get_json, "/frontend/athletes/current")
        athlete = data.get("currentAthlete") if isinstance(data, dict) else None
        if not athlete:
            raise SessionExpiredError("Not logged in to Strava (or the login has expired).")
        try:
            return int(athlete["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError("Could not determine the logged-in athlete.") from exc

    def iter_activity_pages(
        self, *, stop_before: datetime | None = None
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield the logged-in athlete's activities page by page, newest first.

        With ``stop_before`` set, paging stops after the first page that reaches
        activities older than that moment (incremental sync).
        """
        page = 1
        fetched = 0
        while True:
            data = self._call(self._http.get_json, "/athlete/training_activities", {"page": page})
            models = data.get("models") if isinstance(data, dict) else None
            if not isinstance(models, list):
                raise ApiError("Unexpected response from /athlete/training_activities.")
            if not models:
                return
            yield models

            fetched += len(models)
            total = data.get("total")
            log.debug("Page %d: %d activities (%d of %s)", page, len(models), fetched, total)
            if isinstance(total, int) and fetched >= total:
                return
            if stop_before is not None and _reaches(models, stop_before):
                return
            page += 1

    def download_gpx(self, activity_id: int) -> bytes:
        data = self._call(self._http.get_bytes, f"/activities/{activity_id}/export_gpx")
        if not data.lstrip().startswith(b"<?xml"):
            raise ApiError(f"Activity {activity_id}: the GPX export did not return a GPX file.")
        return data

    def _call(self, func: Callable[..., T], *args: Any) -> T:
        for attempt, backoff in enumerate((*THROTTLE_BACKOFF_SECONDS, None), start=1):
            self._pace()
            try:
                return func(*args)
            except ThrottledError:
                if backoff is None:
                    break
                log.warning(
                    "Strava is throttling requests; waiting %d s (attempt %d of %d).",
                    backoff,
                    attempt,
                    len(THROTTLE_BACKOFF_SECONDS),
                )
                self._sleep(backoff)
        raise RateLimitError(
            "Strava keeps throttling requests. Try again later; "
            "everything fetched so far has been saved."
        )

    def _pace(self) -> None:
        """Keep at least ``request_delay`` seconds between requests to be gentle on Strava."""
        now = self._clock()
        if self._last_request is not None:
            remaining = self._request_delay - (now - self._last_request)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request = self._clock()


def _reaches(models: list[dict[str, Any]], moment: datetime) -> bool:
    starts = [start for start in map(start_time_utc, models) if start is not None]
    return bool(starts) and min(starts) < moment

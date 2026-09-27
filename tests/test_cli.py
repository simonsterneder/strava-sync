from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from strava_sync import cli
from strava_sync.browser import Browser
from strava_sync.config import Config, default_config_data, load_config
from strava_sync.exceptions import AthleteMismatchError, LoginError, SessionExpiredError
from strava_sync.storage import ActivityStore

from .conftest import FakeHttp, make_activity, training_page

ATHLETE = {"currentAthlete": {"id": 50392655}}
LOGGED_OUT = {"currentAthlete": None}
BROWSER = Browser("msedge", Path("edge.exe"))


class Harness:
    """Wires `cli.run` to a FakeHttp and records logins."""

    def __init__(self, config: Config, http: FakeHttp) -> None:
        self.config = config
        self.http = http
        self.logins = 0

    def login(self, browser: Browser, profile_dir: Path) -> None:
        self.logins += 1
        profile_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def session(self, browser: Browser, profile_dir: Path) -> Iterator[FakeHttp]:
        yield self.http

    def run(self, **kwargs: Any) -> None:
        cli.run(
            self.config,
            session_factory=self.session,
            login=self.login,
            browser_finder=lambda settings: BROWSER,
            **kwargs,
        )


def _config(tmp_path: Path, **overrides: dict[str, Any]) -> Config:
    path = tmp_path / "config.json"
    data = default_config_data()
    for section, values in overrides.items():
        data[section].update(values)
    path.write_text(json.dumps(data), encoding="utf-8")
    return load_config(path)


@pytest.fixture
def harness(tmp_path: Path, fake_http: FakeHttp) -> Harness:
    return Harness(_config(tmp_path, sync={"request_delay_seconds": 0}), fake_http)


def _count(config: Config) -> int:
    with ActivityStore(config.storage.database) as store:
        return store.count()


def test_first_run_logs_in_syncs_and_exports(harness: Harness) -> None:
    harness.http.responses += [
        ATHLETE,
        training_page([make_activity(2), make_activity(1)], total=2),
    ]

    harness.run()

    assert harness.logins == 1
    assert _count(harness.config) == 2
    assert harness.config.storage.csv_file.read_text(encoding="utf-8-sig").startswith("id;name;")


def test_later_runs_reuse_login_and_sync_incrementally(harness: Harness) -> None:
    harness.http.responses += [ATHLETE, training_page([make_activity(1)], total=1)]
    harness.run()
    newest_page = [
        make_activity(3, start_time="2026-09-28T07:00:00+0000"),
        make_activity(1),
        make_activity(0, start_time="2026-08-01T07:00:00+0000"),  # older than the overlap
    ]
    harness.http.responses += [ATHLETE, training_page(newest_page, total=50)]

    harness.run()

    assert harness.logins == 1
    assert _count(harness.config) == 3
    # Incremental: stopped after the first page because it reached known activities.
    assert harness.http.calls[-1] == ("/athlete/training_activities", {"page": 1})


def test_expired_login_triggers_one_new_login(harness: Harness) -> None:
    harness.config.browser.profile_dir.mkdir(parents=True)
    harness.http.responses += [
        SessionExpiredError("expired"),
        ATHLETE,
        training_page([], total=0),
    ]

    harness.run()

    assert harness.logins == 1


def test_login_that_did_not_work_is_reported(harness: Harness) -> None:
    harness.http.responses += [LOGGED_OUT]

    with pytest.raises(LoginError, match="e-mail address"):
        harness.run()
    assert harness.logins == 1


def test_athlete_mismatch_is_rejected(tmp_path: Path, fake_http: FakeHttp) -> None:
    config = _config(tmp_path, strava={"athlete_id": 1}, sync={"request_delay_seconds": 0})
    harness = Harness(config, fake_http)
    fake_http.responses.append(ATHLETE)

    with pytest.raises(AthleteMismatchError, match="--relogin"):
        harness.run()


def test_relogin_discards_the_stored_profile(harness: Harness) -> None:
    profile = harness.config.browser.profile_dir
    profile.mkdir(parents=True)
    (profile / "Cookies").write_text("old", encoding="utf-8")
    harness.http.responses += [ATHLETE, training_page([], total=0)]

    harness.run(relogin=True)

    assert harness.logins == 1
    assert not (profile / "Cookies").exists()


def test_gpx_download(tmp_path: Path, fake_http: FakeHttp) -> None:
    config = _config(tmp_path, sync={"request_delay_seconds": 0, "download_gpx": True})
    harness = Harness(config, fake_http)
    fake_http.responses += [
        ATHLETE,
        training_page([make_activity(2), make_activity(1, has_latlng=False)], total=2),
        b'<?xml version="1.0"?><gpx/>',
    ]

    harness.run()

    gpx = config.storage.gpx_dir / "2.gpx"
    assert gpx.read_bytes().startswith(b"<?xml")
    assert ("/activities/1/export_gpx", None) not in fake_http.calls


def test_export_only_needs_no_browser(harness: Harness) -> None:
    cli.run(harness.config, export_only=True, browser_finder=_fail)

    assert harness.config.storage.csv_file.exists()


def test_main_reports_errors_with_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def failing_run(config: Config, **kwargs: Any) -> None:
        raise LoginError("nope")

    monkeypatch.setattr(cli, "run", failing_run)
    caplog.set_level("INFO", logger="strava_sync")

    assert cli.main(["-c", str(tmp_path / "config.json")]) == 1
    assert (tmp_path / "config.json").exists()
    assert "Created" in caplog.text
    assert "Error: nope" in caplog.text


def _fail(settings: Any) -> Browser:
    raise AssertionError("browser must not be needed")

"""Command-line interface and the sync workflow behind ``python main.py``."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import timedelta
from pathlib import Path

from . import __version__
from .browser import Browser, WebSession, find_browser, interactive_login
from .client import HttpSession, StravaWebClient
from .config import DEFAULT_CONFIG_FILE, BrowserSettings, Config, load_or_create_config
from .exceptions import (
    ApiError,
    AthleteMismatchError,
    LoginError,
    RateLimitError,
    SessionExpiredError,
    StravaSyncError,
)
from .storage import ActivityStore

log = logging.getLogger("strava_sync")

SessionFactory = Callable[[Browser, Path], AbstractContextManager[HttpSession]]
LoginFunction = Callable[[Browser, Path], None]
BrowserFinder = Callable[[BrowserSettings], Browser]


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _configure_logging(args.verbose)
    try:
        config, created = load_or_create_config(args.config)
        if created:
            log.info("Created %s with default settings; edit it to customise.\n", config.path)
        run(
            config,
            full=args.full,
            relogin=args.relogin,
            export_only=args.export_only,
        )
    except StravaSyncError as exc:
        log.error("Error: %s", exc)
        return 1
    except KeyboardInterrupt:
        log.warning("Interrupted. Everything fetched so far has been saved.")
        return 130
    return 0


def run(
    config: Config,
    *,
    full: bool = False,
    relogin: bool = False,
    export_only: bool = False,
    session_factory: SessionFactory = WebSession,
    login: LoginFunction = interactive_login,
    browser_finder: BrowserFinder = find_browser,
) -> None:
    with ActivityStore(config.storage.database) as store:
        if not export_only:
            browser = browser_finder(config.browser)
            profile_dir = config.browser.profile_dir
            if relogin and profile_dir.exists():
                log.info("Removing the stored Strava login.")
                shutil.rmtree(profile_dir)
            _sync_with_login(config, store, browser, full, session_factory, login)
        _export(store, config)


def _sync_with_login(
    config: Config,
    store: ActivityStore,
    browser: Browser,
    full: bool,
    session_factory: SessionFactory,
    login: LoginFunction,
) -> None:
    profile_dir = config.browser.profile_dir
    just_logged_in = False
    if not profile_dir.exists():
        login(browser, profile_dir)
        just_logged_in = True

    while True:
        try:
            with session_factory(browser, profile_dir) as http:
                client = StravaWebClient(http, request_delay=config.sync.request_delay_seconds)
                _check_athlete(config, client.current_athlete_id())
                _sync(client, store, config, full)
                if config.sync.download_gpx:
                    _download_gpx(client, store, config)
            return
        except SessionExpiredError as exc:
            if just_logged_in:
                raise LoginError(
                    "Still not logged in after the browser was closed. Log in with your "
                    "e-mail address (not Google/Apple) and keep 'Remember me' checked."
                ) from exc
            log.info("Strava login required.")
            login(browser, profile_dir)
            just_logged_in = True


def _check_athlete(config: Config, athlete_id: int) -> None:
    expected = config.strava.athlete_id
    if expected is not None and expected != athlete_id:
        raise AthleteMismatchError(
            f"Logged in as athlete {athlete_id}, but config.json expects {expected}. "
            "Run `python main.py --relogin` to log in with the right account, "
            "or correct strava.athlete_id."
        )
    log.info("Logged in as athlete %d.", athlete_id)


def _sync(client: StravaWebClient, store: ActivityStore, config: Config, full: bool) -> None:
    latest = None if full else store.latest_start_time()
    stop_before = None
    if latest is None:
        log.info("Downloading all activities ...")
    else:
        # Re-check a few days so late uploads and recent edits are picked up.
        stop_before = latest - timedelta(days=config.sync.overlap_days)
        log.info("Checking for new activities since %s ...", stop_before.date().isoformat())

    fetched = 0
    for page in client.iter_activity_pages(stop_before=stop_before):
        fetched += store.upsert_many(page)
        log.debug("%d activities stored so far", fetched)
    log.info("Fetched %d activities (%d in database).", fetched, store.count())


def _download_gpx(client: StravaWebClient, store: ActivityStore, config: Config) -> None:
    missing = store.ids_missing_gpx()
    if not missing:
        return
    gpx_dir = config.storage.gpx_dir
    gpx_dir.mkdir(parents=True, exist_ok=True)
    log.info("Downloading %d GPX file(s) to %s ...", len(missing), gpx_dir)
    for index, activity_id in enumerate(missing, start=1):
        try:
            data = client.download_gpx(activity_id)
        except RateLimitError:
            raise
        except ApiError as exc:
            log.warning("Skipping GPX for activity %d: %s", activity_id, exc)
            continue
        path = gpx_dir / f"{activity_id}.gpx"
        path.write_bytes(data)
        store.set_gpx_file(activity_id, str(path))
        if index % 10 == 0 or index == len(missing):
            log.info("  %d/%d GPX files", index, len(missing))


def _export(store: ActivityStore, config: Config) -> None:
    path = config.storage.csv_file
    count = store.export_csv(
        path, delimiter=config.storage.csv_delimiter, encoding=config.storage.csv_encoding
    )
    log.info("Exported %d activities to %s", count, path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Back up your own Strava activities to SQLite and CSV.",
    )
    parser.add_argument("--version", action="version", version=f"strava-sync {__version__}")
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_FILE,
        help="configuration file, created on first run (default: ./config.json)",
    )
    parser.add_argument("--full", action="store_true", help="re-download all activities")
    parser.add_argument(
        "--relogin",
        action="store_true",
        help="forget the stored login and log in again (e.g. to switch accounts)",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="only rewrite the CSV file from the local database",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="enable debug output")
    return parser


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s" if verbose else "%(message)s",
        stream=sys.stdout,
    )

from __future__ import annotations

import json
from pathlib import Path

import pytest

from strava_sync.config import (
    BrowserSettings,
    SyncSettings,
    default_config_data,
    load_config,
    load_or_create_config,
)
from strava_sync.exceptions import ConfigError


def _write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_first_run_creates_config_with_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.json"

    config, created = load_or_create_config(path)

    assert created
    assert json.loads(path.read_text(encoding="utf-8")) == default_config_data()
    assert config.strava.athlete_id is None
    assert config.sync == SyncSettings()
    assert config.browser.name == "auto"


def test_existing_config_is_not_overwritten(tmp_path: Path) -> None:
    path = _write(tmp_path / "config.json", {"strava": {"athlete_id": 1}})

    config, created = load_or_create_config(path)

    assert not created
    assert config.strava.athlete_id == 1


def test_relative_paths_resolve_against_config_dir(tmp_path: Path) -> None:
    config, _ = load_or_create_config(tmp_path / "sub" / "config.json")

    base = (tmp_path / "sub").resolve()
    assert config.storage.database == base / "data" / "strava.db"
    assert config.browser.profile_dir == base / "data" / "browser-profile"


def test_reads_all_sections(tmp_path: Path) -> None:
    exe = tmp_path / "edge.exe"
    path = _write(
        tmp_path / "config.json",
        {
            "strava": {"athlete_id": "50392655"},
            "browser": {"name": "chrome", "executable": str(exe), "profile_dir": "p"},
            "sync": {
                "overlap_days": 0,
                "request_delay_seconds": 0,
                "download_gpx": True,
            },
            "storage": {"csv_file": "out/a.csv", "csv_delimiter": ","},
        },
    )

    config = load_config(path)

    assert config.strava.athlete_id == 50392655
    assert config.browser == BrowserSettings("chrome", exe, (tmp_path / "p").resolve())
    assert config.sync == SyncSettings(0, 0.0, True)
    assert config.storage.csv_file == (tmp_path / "out" / "a.csv").resolve()
    assert config.storage.csv_delimiter == ","


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (50392655, 50392655),
        ("50392655", 50392655),
        (" https://www.strava.com/athletes/50392655 ", 50392655),
        ("https://www.strava.com/athletes/50392655/training", 50392655),
        (None, None),
        ("", None),
    ],
)
def test_athlete_id_formats(tmp_path: Path, value: object, expected: int | None) -> None:
    path = _write(tmp_path / "c.json", {"strava": {"athlete_id": value}})

    assert load_config(path).strava.athlete_id == expected


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"strava": {"athlete_id": "abc"}}, "athlete id"),
        ({"strava": {"athlete_id": -5}}, "athlete id"),
        ({"strava": {"athlete_id": True}}, "athlete id"),
        ({"strava": {"athleteid": 1}}, "Unknown setting"),
        ({"database": {}}, "Unknown section"),
        ({"browser": {"name": "firefox"}}, "browser.name"),
        ({"browser": {"executable": 5}}, "browser.executable"),
        ({"sync": {"overlap_days": -1}}, ">= 0"),
        ({"sync": {"overlap_days": "7"}}, "must be an integer"),
        ({"sync": {"request_delay_seconds": -1}}, ">= 0.0"),
        ({"sync": {"download_gpx": "yes"}}, "true or false"),
        ({"storage": {"csv_delimiter": ";;"}}, "single character"),
        ({"storage": {"csv_encoding": "klingon"}}, "unknown encoding"),
        ({"storage": {"database": ""}}, "non-empty path"),
        ({"sync": []}, "must be a JSON object"),
        ([], "top level"),
    ],
)
def test_invalid_values_are_rejected(tmp_path: Path, data: object, message: str) -> None:
    path = _write(tmp_path / "c.json", data)

    with pytest.raises(ConfigError, match=message):
        load_config(path)


def test_invalid_json_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "c.json"
    path.write_text("{ not json", encoding="utf-8")

    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(path)

"""Loading and validation of ``config.json``.

All user-facing settings live in one JSON file. It is created with defaults on the
first run, so it only needs editing to change something. Relative paths inside it are
resolved against the directory of the config file, which keeps scheduled runs
independent of the current working directory.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .exceptions import ConfigError

DEFAULT_CONFIG_FILE = Path("config.json")
SUPPORTED_BROWSERS = ("auto", "msedge", "chrome")

# Keys accepted per section; anything else is reported as a typo.
_ALLOWED_KEYS: dict[str, frozenset[str]] = {
    "strava": frozenset({"athlete_id"}),
    "browser": frozenset({"name", "executable", "profile_dir"}),
    "sync": frozenset({"overlap_days", "request_delay_seconds", "download_gpx"}),
    "storage": frozenset({"database", "csv_file", "gpx_dir", "csv_delimiter", "csv_encoding"}),
}
_ATHLETE_URL = re.compile(r"strava\.com/athletes/(\d+)")


@dataclass(frozen=True)
class StravaSettings:
    athlete_id: int | None = None


@dataclass(frozen=True)
class BrowserSettings:
    name: str = "auto"
    executable: Path | None = None
    profile_dir: Path = Path("data/browser-profile")


@dataclass(frozen=True)
class SyncSettings:
    overlap_days: int = 7
    request_delay_seconds: float = 1.0
    download_gpx: bool = False


@dataclass(frozen=True)
class StorageSettings:
    database: Path = Path("data/strava.db")
    csv_file: Path = Path("data/activities.csv")
    gpx_dir: Path = Path("data/gpx")
    csv_delimiter: str = ";"
    csv_encoding: str = "utf-8-sig"


@dataclass(frozen=True)
class Config:
    path: Path
    strava: StravaSettings
    browser: BrowserSettings
    sync: SyncSettings
    storage: StorageSettings


def default_config_data() -> dict[str, Any]:
    """Return a complete config document populated with the default settings."""
    browser, sync, storage = BrowserSettings(), SyncSettings(), StorageSettings()
    return {
        "strava": {"athlete_id": None},
        "browser": {
            "name": browser.name,
            "executable": None,
            "profile_dir": browser.profile_dir.as_posix(),
        },
        "sync": {
            "overlap_days": sync.overlap_days,
            "request_delay_seconds": sync.request_delay_seconds,
            "download_gpx": sync.download_gpx,
        },
        "storage": {
            "database": storage.database.as_posix(),
            "csv_file": storage.csv_file.as_posix(),
            "gpx_dir": storage.gpx_dir.as_posix(),
            "csv_delimiter": storage.csv_delimiter,
            "csv_encoding": storage.csv_encoding,
        },
    }


def load_or_create_config(path: Path | str = DEFAULT_CONFIG_FILE) -> tuple[Config, bool]:
    """Load ``path``; if it does not exist, write the defaults first.

    Returns the config and whether the file was newly created.
    """
    config_path = Path(path).expanduser().resolve()
    created = False
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(default_config_data(), indent=2) + "\n", "utf-8")
        created = True
    return load_config(config_path), created


def load_config(path: Path | str) -> Config:
    config_path = Path(path).expanduser().resolve()
    base_dir = config_path.parent
    raw = _read_json(config_path)

    unknown = raw.keys() - _ALLOWED_KEYS.keys()
    if unknown:
        raise ConfigError(f"Unknown section(s) in {config_path.name}: {', '.join(sorted(unknown))}")

    strava = _section(raw, "strava")
    browser = _section(raw, "browser")
    sync = _section(raw, "sync")
    storage = _section(raw, "storage")
    browser_defaults, sync_defaults, storage_defaults = (
        BrowserSettings(),
        SyncSettings(),
        StorageSettings(),
    )

    return Config(
        path=config_path,
        strava=StravaSettings(athlete_id=_athlete_id(strava.get("athlete_id"))),
        browser=BrowserSettings(
            name=_browser_name(browser.get("name", browser_defaults.name)),
            executable=_optional_path(browser, "browser.executable", base_dir),
            profile_dir=_path(
                browser, "browser.profile_dir", browser_defaults.profile_dir, base_dir
            ),
        ),
        sync=SyncSettings(
            overlap_days=_int(sync, "sync.overlap_days", sync_defaults.overlap_days, minimum=0),
            request_delay_seconds=_float(
                sync, "sync.request_delay_seconds", sync_defaults.request_delay_seconds, 0.0
            ),
            download_gpx=_bool(sync, "sync.download_gpx", sync_defaults.download_gpx),
        ),
        storage=StorageSettings(
            database=_path(storage, "storage.database", storage_defaults.database, base_dir),
            csv_file=_path(storage, "storage.csv_file", storage_defaults.csv_file, base_dir),
            gpx_dir=_path(storage, "storage.gpx_dir", storage_defaults.gpx_dir, base_dir),
            csv_delimiter=_delimiter(storage, storage_defaults.csv_delimiter),
            csv_encoding=_encoding(storage, storage_defaults.csv_encoding),
        ),
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path.name} is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise ConfigError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} must contain a JSON object at the top level.")
    return data


def _section(raw: Mapping[str, Any], name: str) -> dict[str, Any]:
    section = raw.get(name, {})
    if not isinstance(section, dict):
        raise ConfigError(f"'{name}' must be a JSON object.")
    unknown = section.keys() - _ALLOWED_KEYS[name]
    if unknown:
        raise ConfigError(f"Unknown setting(s) in '{name}': {', '.join(sorted(unknown))}")
    return section


def _athlete_id(value: Any) -> int | None:
    """Accept a number, a numeric string or a profile URL such as .../athletes/123."""
    if value is None or value == "":
        return None
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    if isinstance(value, str):
        text = value.strip()
        match = _ATHLETE_URL.search(text)
        if match:
            return int(match.group(1))
        if text.isdigit() and int(text) > 0:
            return int(text)
    raise ConfigError(
        "strava.athlete_id must be your Strava athlete id (e.g. 12345678), "
        "your profile URL or null."
    )


def _browser_name(value: Any) -> str:
    if value not in SUPPORTED_BROWSERS:
        raise ConfigError(f"browser.name must be one of: {', '.join(SUPPORTED_BROWSERS)}.")
    return str(value)


def _key(name: str) -> str:
    return name.split(".")[-1]


def _int(section: Mapping[str, Any], name: str, default: int, *, minimum: int) -> int:
    value = section.get(_key(name), default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{name} must be an integer.")
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}.")
    return value


def _float(section: Mapping[str, Any], name: str, default: float, minimum: float) -> float:
    value = section.get(_key(name), default)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigError(f"{name} must be a number.")
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}, got {value}.")
    return float(value)


def _bool(section: Mapping[str, Any], name: str, default: bool) -> bool:
    value = section.get(_key(name), default)
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be true or false.")
    return value


def _path(section: Mapping[str, Any], name: str, default: Path, base_dir: Path) -> Path:
    value = section.get(_key(name), default.as_posix())
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be a non-empty path string.")
    return _resolve(value, base_dir)


def _optional_path(section: Mapping[str, Any], name: str, base_dir: Path) -> Path | None:
    value = section.get(_key(name))
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ConfigError(f"{name} must be a path string or null.")
    return _resolve(value, base_dir)


def _resolve(value: str, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (base_dir / path).resolve()


def _delimiter(section: Mapping[str, Any], default: str) -> str:
    value = section.get("csv_delimiter", default)
    if not isinstance(value, str) or len(value) != 1:
        raise ConfigError("storage.csv_delimiter must be a single character.")
    return value


def _encoding(section: Mapping[str, Any], default: str) -> str:
    value = section.get("csv_encoding", default)
    if not isinstance(value, str):
        raise ConfigError("storage.csv_encoding must be a string.")
    try:
        "".encode(value)
    except LookupError as exc:
        raise ConfigError(f"storage.csv_encoding: unknown encoding '{value}'.") from exc
    return value

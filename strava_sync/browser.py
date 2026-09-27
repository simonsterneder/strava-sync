"""Browser handling: one-time interactive login and headless access to strava.com.

The login happens in a regular, *non-automated* browser window started with a
dedicated profile directory. Google and Strava refuse sign-ins from automated
browsers, and a normal window is also what the user expects to see. Once the user
has logged in with "Remember me" checked, Strava stores long-lived cookies in that
profile. Later runs open the same profile headlessly through Playwright and issue
plain HTTP requests with it; the cookies never leave the browser's own encrypted
storage.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any

from .config import BrowserSettings
from .exceptions import ApiError, BrowserNotFoundError, SessionExpiredError, ThrottledError

if TYPE_CHECKING:
    from playwright.sync_api import APIResponse, BrowserContext, Playwright

log = logging.getLogger(__name__)

BASE_URL = "https://www.strava.com"
LOGIN_URL = f"{BASE_URL}/login"
REQUEST_TIMEOUT_SECONDS = 30
_XHR_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


@dataclass(frozen=True)
class Browser:
    channel: str  # "msedge" or "chrome"
    executable: Path


def _candidates(channel: str) -> list[str]:
    """Well-known install locations (or PATH names) per browser and platform."""
    if sys.platform == "win32":
        roots = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        relative = (
            r"Microsoft\Edge\Application\msedge.exe"
            if channel == "msedge"
            else r"Google\Chrome\Application\chrome.exe"
        )
        return [str(Path(root) / relative) for root in roots if root]
    if sys.platform == "darwin":
        app = "Microsoft Edge" if channel == "msedge" else "Google Chrome"
        return [f"/Applications/{app}.app/Contents/MacOS/{app}"]
    if channel == "msedge":
        return ["microsoft-edge", "microsoft-edge-stable"]
    return ["google-chrome", "google-chrome-stable"]


def find_browser(
    settings: BrowserSettings, which: Callable[[str], str | None] = shutil.which
) -> Browser:
    channels = ("msedge", "chrome") if settings.name == "auto" else (settings.name,)

    if settings.executable is not None:
        if not settings.executable.exists():
            raise BrowserNotFoundError(f"browser.executable does not exist: {settings.executable}")
        channel = "msedge" if settings.name == "auto" else settings.name
        return Browser(channel, settings.executable)

    for channel in channels:
        for candidate in _candidates(channel):
            path = Path(candidate) if Path(candidate).is_absolute() else None
            if path is not None and path.exists():
                return Browser(channel, path)
            if path is None and (found := which(candidate)):
                return Browser(channel, Path(found))

    raise BrowserNotFoundError(
        "Neither Microsoft Edge nor Google Chrome was found. Install one of them or set "
        "browser.executable in config.json to the browser's executable."
    )


def interactive_login(
    browser: Browser,
    profile_dir: Path,
    *,
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> None:
    """Open a normal browser window on the Strava login page and wait until it is closed."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    _disable_background_mode(profile_dir)
    quit_hint = "quit the browser (Cmd+Q)" if sys.platform == "darwin" else "close the window"
    log.info(
        "\nA %s window opens for the one-time Strava login:\n"
        "  1. Enter your e-mail address directly. Do NOT use 'Sign in with Google/Apple';\n"
        "     Google blocks those sign-ins in windows opened by other programs.\n"
        "  2. Keep 'Remember me' checked.\n"
        "  3. After logging in, %s to continue here.\n",
        "Microsoft Edge" if browser.channel == "msedge" else "Google Chrome",
        quit_hint,
    )
    process = popen(
        [
            str(browser.executable),
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
            LOGIN_URL,
        ]
    )
    process.wait()


def _disable_background_mode(profile_dir: Path) -> None:
    """Keep the browser from lingering in the background after its window is closed.

    Otherwise the process never exits and we would wait forever. Only applies to a
    fresh profile; an existing "Local State" file is left untouched.
    """
    local_state = profile_dir / "Local State"
    if not local_state.exists():
        local_state.write_text(json.dumps({"background_mode": {"enabled": False}}), "utf-8")


class WebSession:
    """Headless HTTP access to strava.com using the logged-in browser profile."""

    def __init__(self, browser: Browser, profile_dir: Path) -> None:
        self._browser = browser
        self._profile_dir = profile_dir
        self._timeout_ms = REQUEST_TIMEOUT_SECONDS * 1000
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None

    def __enter__(self) -> WebSession:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                str(self._profile_dir),
                executable_path=str(self._browser.executable),
                headless=True,
            )
        except PlaywrightError as exc:
            self._playwright.stop()
            raise ApiError(
                f"Could not start the browser in the background: {exc.message.splitlines()[0]}. "
                "Make sure no other window is using the strava-sync browser profile."
            ) from exc
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()

    def get_json(self, path: str, params: Mapping[str, str | int] | None = None) -> Any:
        response = self._get(path, params, _XHR_HEADERS)
        if "json" not in response.headers.get("content-type", ""):
            raise ApiError(f"GET {path}: expected JSON, got {response.headers.get('content-type')}")
        return response.json()

    def get_bytes(self, path: str) -> bytes:
        return self._get(path, None, {}).body()

    def _get(
        self, path: str, params: Mapping[str, str | int] | None, headers: Mapping[str, str]
    ) -> APIResponse:
        from playwright.sync_api import Error as PlaywrightError

        assert self._context is not None, "WebSession must be used as a context manager"
        try:
            response = self._context.request.get(
                BASE_URL + path,
                params=dict(params) if params else None,
                headers=dict(headers),
                timeout=self._timeout_ms,
                max_redirects=0,
            )
        except PlaywrightError as exc:
            raise ApiError(f"Request to Strava failed: {exc.message.splitlines()[0]}") from exc

        location = response.headers.get("location", "")
        if response.status == 401 or (300 <= response.status < 400 and "/login" in location):
            raise SessionExpiredError("Not logged in to Strava (or the login has expired).")
        if response.status == 429:
            raise ThrottledError(f"Strava is throttling requests (HTTP 429) for {path}.")
        if not response.ok:
            raise ApiError(f"GET {path} failed with HTTP {response.status}.")
        return response

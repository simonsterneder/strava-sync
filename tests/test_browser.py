from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from strava_sync import browser as browser_module
from strava_sync.browser import LOGIN_URL, Browser, WebSession, find_browser, interactive_login
from strava_sync.config import BrowserSettings
from strava_sync.exceptions import (
    ApiError,
    BrowserNotFoundError,
    SessionExpiredError,
    ThrottledError,
)


def _no_which(name: str) -> str | None:
    return None


def test_explicit_executable_wins(tmp_path: Path) -> None:
    exe = tmp_path / "chrome.exe"
    exe.touch()

    found = find_browser(BrowserSettings(name="chrome", executable=exe), which=_no_which)

    assert found == Browser("chrome", exe)


def test_missing_explicit_executable(tmp_path: Path) -> None:
    with pytest.raises(BrowserNotFoundError, match="does not exist"):
        find_browser(BrowserSettings(executable=tmp_path / "nope.exe"), which=_no_which)


def test_auto_prefers_edge_then_chrome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chrome = tmp_path / "chrome"
    chrome.touch()
    candidates = {"msedge": [str(tmp_path / "missing-edge")], "chrome": [str(chrome)]}
    monkeypatch.setattr(browser_module, "_candidates", lambda channel: candidates[channel])

    assert find_browser(BrowserSettings(), which=_no_which) == Browser("chrome", chrome)


def test_finds_browser_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser_module, "_candidates", lambda channel: [f"{channel}-bin"])
    which = {"msedge-bin": "/usr/bin/microsoft-edge"}.get

    assert find_browser(BrowserSettings(), which=which) == Browser(
        "msedge", Path("/usr/bin/microsoft-edge")
    )


def test_no_browser_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser_module, "_candidates", lambda channel: [])

    with pytest.raises(BrowserNotFoundError, match="Neither Microsoft Edge nor Google Chrome"):
        find_browser(BrowserSettings(), which=_no_which)


def test_interactive_login_opens_plain_browser_and_waits(tmp_path: Path) -> None:
    launched: list[list[str]] = []

    class FakeProcess:
        waited = False

        def wait(self) -> int:
            FakeProcess.waited = True
            return 0

    def popen(args: list[str], **kwargs: Any) -> FakeProcess:
        launched.append(args)
        return FakeProcess()

    profile = tmp_path / "profile"
    interactive_login(Browser("msedge", Path("edge.exe")), profile, popen=popen)  # type: ignore[arg-type]

    (args,) = launched
    assert args[0] == "edge.exe"
    assert f"--user-data-dir={profile}" in args
    assert args[-1] == LOGIN_URL
    # No automation switches: this must be an ordinary browser window.
    assert not any("automation" in arg or "remote-debugging" in arg for arg in args)
    assert FakeProcess.waited
    local_state = json.loads((profile / "Local State").read_text(encoding="utf-8"))
    assert local_state == {"background_mode": {"enabled": False}}


class _FakeResponse:
    def __init__(self, status: int, headers: dict[str, str] | None = None, body: Any = None):
        self.status = status
        self.headers = headers or {}
        self._body = body

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def json(self) -> Any:
        return self._body

    def body(self) -> bytes:
        return bytes(self._body)


class _FakeRequest:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append((url, kwargs))
        return self.response


def _session_with(response: _FakeResponse) -> tuple[WebSession, _FakeRequest]:
    session = WebSession(Browser("msedge", Path("edge.exe")), Path("profile"))
    request = _FakeRequest(response)
    session._context = SimpleNamespace(request=request)  # type: ignore[assignment]
    return session, request


def test_get_json_sends_xhr_request_without_following_redirects() -> None:
    json_type = {"content-type": "application/json; charset=utf-8"}
    session, request = _session_with(_FakeResponse(200, json_type, {"models": []}))

    assert session.get_json("/athlete/training_activities", {"page": 2}) == {"models": []}
    ((url, kwargs),) = request.calls
    assert url == "https://www.strava.com/athlete/training_activities"
    assert kwargs["params"] == {"page": 2}
    assert kwargs["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert kwargs["max_redirects"] == 0
    assert kwargs["timeout"] == 30_000


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (_FakeResponse(401), SessionExpiredError),
        (_FakeResponse(302, {"location": "https://www.strava.com/login"}), SessionExpiredError),
        (_FakeResponse(429), ThrottledError),
        (_FakeResponse(500), ApiError),
        (_FakeResponse(200, {"content-type": "text/html"}), ApiError),
    ],
)
def test_get_json_maps_failures(response: _FakeResponse, error: type[Exception]) -> None:
    session, _ = _session_with(response)

    with pytest.raises(error):
        session.get_json("/frontend/athletes/current")


def test_get_bytes() -> None:
    session, request = _session_with(_FakeResponse(200, {}, b"<?xml?>"))

    assert session.get_bytes("/activities/1/export_gpx") == b"<?xml?>"
    assert "X-Requested-With" not in request.calls[0][1]["headers"]


def test_interactive_login_keeps_existing_local_state(tmp_path: Path) -> None:
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "Local State").write_text('{"existing": true}', encoding="utf-8")

    class FakeProcess:
        def wait(self) -> int:
            return 0

    interactive_login(
        Browser("chrome", Path("chrome")),
        profile,
        popen=lambda *args, **kwargs: FakeProcess(),  # type: ignore[arg-type,return-value]
    )

    assert (profile / "Local State").read_text(encoding="utf-8") == '{"existing": true}'

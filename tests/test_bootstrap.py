from __future__ import annotations

import subprocess
from typing import Any

import pytest

from strava_sync import bootstrap


class _Stdin:
    def __init__(self, tty: bool) -> None:
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_nothing_to_do_when_dependencies_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap, "missing_modules", lambda: [])

    bootstrap.ensure_dependencies()


def test_non_interactive_prints_install_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap, "missing_modules", lambda: ["playwright"])
    monkeypatch.setattr("sys.stdin", _Stdin(tty=False))

    with pytest.raises(SystemExit, match="pip install -r"):
        bootstrap.ensure_dependencies()


def test_closed_input_prints_install_command(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_input(prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr(bootstrap, "missing_modules", lambda: ["playwright"])
    monkeypatch.setattr("sys.stdin", _Stdin(tty=True))
    monkeypatch.setattr("builtins.input", no_input)

    with pytest.raises(SystemExit, match="pip install -r"):
        bootstrap.ensure_dependencies()


def test_user_declines_installation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap, "missing_modules", lambda: ["playwright"])
    monkeypatch.setattr("sys.stdin", _Stdin(tty=True))
    monkeypatch.setattr("builtins.input", lambda prompt: "n")

    with pytest.raises(SystemExit, match="Aborted"):
        bootstrap.ensure_dependencies()


def test_user_accepts_installation(monkeypatch: pytest.MonkeyPatch) -> None:
    missing = [["playwright"], []]
    commands: list[list[str]] = []

    def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(bootstrap, "missing_modules", lambda: missing.pop(0))
    monkeypatch.setattr("sys.stdin", _Stdin(tty=True))
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    monkeypatch.setattr(subprocess, "run", run)

    bootstrap.ensure_dependencies()

    ((cmd),) = commands
    assert cmd[1:5] == ["-m", "pip", "install", "-r"]
    assert cmd[-1] == str(bootstrap.REQUIREMENTS_FILE)


def test_failed_installation_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap, "missing_modules", lambda: ["playwright"])
    monkeypatch.setattr("sys.stdin", _Stdin(tty=True))
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 1)
    )

    with pytest.raises(SystemExit, match="Installation failed"):
        bootstrap.ensure_dependencies()


def test_missing_modules_detects_real_packages() -> None:
    assert bootstrap.missing_modules() == []  # playwright is installed in the test env

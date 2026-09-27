"""First-run helper that installs missing dependencies, so ``python main.py`` just works.

Deliberately uses only the standard library: it runs before any dependency exists.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REQUIREMENTS_FILE = Path(__file__).resolve().parent.parent / "requirements.txt"
REQUIRED_MODULES = ("playwright",)


def missing_modules() -> list[str]:
    return [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]


def ensure_dependencies() -> None:
    missing = missing_modules()
    if not missing:
        return

    install_cmd = [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)]
    manual = "Install them with:\n  " + " ".join(install_cmd)
    print(f"Missing Python package(s): {', '.join(missing)}")
    if not sys.stdin.isatty():
        sys.exit(manual)

    try:
        answer = input("Install them now? [Y/n] ").strip().lower()
    except EOFError:
        # Windows reports redirected input such as NUL as a terminal, so isatty()
        # alone cannot detect non-interactive runs (e.g. from Task Scheduler).
        print()
        sys.exit(manual)
    if answer not in ("", "y", "yes", "j", "ja"):
        sys.exit("Aborted. " + manual)

    result = subprocess.run(install_cmd, check=False)
    if result.returncode != 0 or missing_modules():
        sys.exit("Installation failed. See the pip output above.")
    print()

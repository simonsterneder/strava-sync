#!/usr/bin/env python3
"""Entry point: ``python main.py``.

Checks the Python version, offers to install missing dependencies and then runs the
strava-sync command line interface. Pass ``--help`` for all options.
"""

import sys

if sys.version_info < (3, 10):  # noqa: UP036 - must run before any modern syntax is parsed
    sys.exit("strava-sync requires Python 3.10 or newer.")

from strava_sync.bootstrap import ensure_dependencies

ensure_dependencies()

from strava_sync.cli import main  # noqa: E402 - imports playwright, so only after the check

sys.exit(main())

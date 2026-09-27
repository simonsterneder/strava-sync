# strava-sync

[![CI](https://github.com/simonsterneder/strava-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/simonsterneder/strava-sync/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Back up **your own** Strava activities to a local SQLite database and a CSV file, and
optionally download a GPX file for every activity.

- **No paid subscription.** Since June 2026, Strava's official API requires a paid Strava
  subscription. strava-sync reads the same data the "My Activities" page shows you in the
  browser, so a free account is enough.
- **Log in once.** The first run opens a normal browser window for the Strava login. Every
  later run works in the background without any interaction, so it can run on a schedule.
- **Incremental.** Later runs only fetch what is new, plus a configurable overlap to catch
  late uploads and edits.
- **Gentle.** Requests are paced, and the tool backs off when Strava throttles.
- **Excel-friendly CSV** with derived columns (km, h:mm:ss, pace, km/h). The complete raw data
  of every activity is kept in the database.
- Works with the **Microsoft Edge or Google Chrome** you already have installed. No extra
  browser download is needed.

> [!IMPORTANT]
> strava-sync is an unofficial tool that automates access to strava.com. Strava's
> [terms of service](https://www.strava.com/legal/terms) do not allow automated access to the
> website. Use it only for your own account, at your own risk, and keep the default request
> pacing. Because it relies on the website's internal endpoints, a change on Strava's side can
> break it until it is updated.

---

## Quick start

Requirements: **Python 3.10+** and **Microsoft Edge** or **Google Chrome**.

```bash
git clone https://github.com/simonsterneder/strava-sync.git
cd strava-sync
python main.py
```

That's it. On the first start, `main.py`:

1. offers to install the one required package (`playwright`),
2. creates `config.json` with default settings,
3. opens a browser window for the one-time Strava login (see below),
4. downloads all your activities to `data/strava.db` and `data/activities.csv`.

Run `python main.py` again whenever you want to update. It takes a few seconds and needs no login.

> [!TIP]
> To keep the package out of your global Python, create a virtual environment first:
> `python -m venv .venv`, then activate it (`.venv\Scripts\activate` on Windows,
> `source .venv/bin/activate` on macOS/Linux) and run `python main.py`.

### The one-time login

A regular browser window with the Strava login page opens. It uses a separate profile, so your
normal browser, its passwords and other logins are not touched.

1. **Enter your e-mail address directly** in the Strava form. Do **not** use "Sign in with
   Google" or "Sign in with Apple": Google blocks those sign-ins in windows opened by other
   programs. If you normally sign in via Google, request a one-time code by e-mail, or set a
   Strava password under *Settings → My Account*.
2. Keep **"Remember me"** checked. This keeps you logged in for later runs.
3. After the dashboard appears, **close the window** (on macOS: quit the browser with Cmd+Q).

strava-sync continues automatically. If Strava ever ends the session, the next run opens the
login window again.

## Usage

```text
python main.py [--full] [--relogin] [--export-only] [-c CONFIG] [-v]
```

| Option            | Description                                                         |
|-------------------|---------------------------------------------------------------------|
| *(none)*          | Fetch new activities and update the CSV file                        |
| `--full`          | Re-download all activities (e.g. after editing many old activities) |
| `--relogin`       | Forget the stored login and log in again, e.g. to switch accounts   |
| `--export-only`   | Only rewrite the CSV file from the local database                   |
| `-c`, `--config`  | Use a different configuration file (default: `./config.json`)       |
| `-v`, `--verbose` | Debug output                                                        |

The exit code is `0` on success and `1` on errors, so scripts and schedulers can check it.

## Configuration

`config.json` is created on the first run. Edit it only if you want to change something.
Relative paths are resolved against the folder that contains `config.json`. Unknown keys are
rejected to catch typos.

```json
{
  "strava": {
    "athlete_id": null
  },
  "browser": {
    "name": "auto",
    "executable": null,
    "profile_dir": "data/browser-profile"
  },
  "sync": {
    "overlap_days": 7,
    "request_delay_seconds": 1.0,
    "download_gpx": false
  },
  "storage": {
    "database": "data/strava.db",
    "csv_file": "data/activities.csv",
    "gpx_dir": "data/gpx",
    "csv_delimiter": ";",
    "csv_encoding": "utf-8-sig"
  }
}
```

| Key                             | Default                | Description |
|---------------------------------|------------------------|-------------|
| `strava.athlete_id`             | `null`                 | Your athlete id (the number in `strava.com/athletes/<id>`) or your full profile URL. If set, strava-sync refuses to sync when a different account is logged in. |
| `browser.name`                  | `auto`                 | `auto` (Edge, then Chrome), `msedge` or `chrome` |
| `browser.executable`            | `null`                 | Path to the browser executable, if it is installed in an unusual place |
| `browser.profile_dir`           | `data/browser-profile` | Separate browser profile that holds the Strava login |
| `sync.overlap_days`             | `7`                    | On incremental runs, re-check activities from this many days before the newest stored one |
| `sync.request_delay_seconds`    | `1.0`                  | Minimum pause between two requests to Strava |
| `sync.download_gpx`             | `false`                | Also download a GPX file for every activity with a GPS track. The first run then takes about one second per activity. |
| `storage.database`              | `data/strava.db`       | SQLite database |
| `storage.csv_file`              | `data/activities.csv`  | CSV export |
| `storage.gpx_dir`               | `data/gpx`             | Folder for GPX files (`<activity id>.gpx`) |
| `storage.csv_delimiter`         | `;`                    | CSV delimiter. `;` opens correctly in Excel with German or European locale settings. |
| `storage.csv_encoding`          | `utf-8-sig`            | CSV encoding. `utf-8-sig` adds a BOM so Excel detects UTF-8. |

## Data

### CSV columns

`id`, `name`, `sport_type`, `start_time_utc`, `start_time_local`, `distance_m`,
`moving_time_s`, `elapsed_time_s`, `elevation_gain_m`, `relative_effort`, `commute`, `trainer`,
`private`, `visibility`, `gear_id`, `bike_id`, `has_gps`, `description`, `url`, `gpx_file`,
and the derived columns `distance_km`, `moving_time` (h:mm:ss), `pace_min_per_km` and
`speed_kmh`.

Heart rate and cadence are not part of Strava's activity list. Enable `sync.download_gpx` to get
them: Strava's GPX export includes them per track point when your device recorded them.

### Querying the database

The `raw_json` column holds the complete record Strava returned for every activity.

```sql
SELECT strftime('%Y', start_time_local) AS year,
       sport_type,
       COUNT(*)                         AS activities,
       ROUND(SUM(distance_m) / 1000)    AS km
FROM activities
GROUP BY year, sport_type
ORDER BY year, km DESC;
```

## Running on a schedule

Log in once interactively (`python main.py`). After that, scheduled runs need no interaction.
If Strava ever ends the session, the next scheduled run opens the login window and waits
until you have logged in again.

Schedulers do not know your `PATH`, so use the full path to Python. `where python` (Windows)
or `which python3` (macOS) prints it. If you use a virtual environment, use its Python instead
(`.venv\Scripts\python.exe` or `.venv/bin/python`).

**Windows (Task Scheduler)**, daily at 06:00. Run this in `cmd` inside the project folder and
replace the Python path:

```bat
schtasks /Create /SC DAILY /ST 06:00 /TN "strava-sync" /TR "\"C:\Path\To\python.exe\" \"%CD%\main.py\" -c \"%CD%\config.json\""
```

**macOS (cron)**, daily at 06:00:

```cron
0 6 * * * cd /path/to/strava-sync && /path/to/python3 main.py >> sync.log 2>&1
```

## How it works

1. **Login:** strava-sync starts your installed Edge or Chrome as a completely normal browser
   window with a dedicated profile folder (`data/browser-profile`) and waits until you close
   it. The window is not remote-controlled. Google and Strava reject logins from automated
   browsers, and you stay in full control of what you enter.
2. **Sync:** later runs open that profile invisibly through
   [Playwright](https://playwright.dev/python/) and request
   `strava.com/athlete/training_activities`, the endpoint behind the "My Activities" page,
   page by page, newest first. Pages are saved as they arrive, so an interrupted run keeps its
   progress.
3. **Storage:** activities are upserted into SQLite by id, so re-running never creates
   duplicates and edits on Strava are picked up.

## Security and privacy

- The Strava login stays in the browser's own encrypted cookie store inside
  `data/browser-profile`. strava-sync never sees or stores your password.
- Anyone who can copy `data/browser-profile` can access your Strava account. Treat the `data`
  folder like a password. It is excluded from git via `.gitignore`.
- To log out, delete `data/browser-profile` or run `python main.py --relogin`. You can also
  end all sessions on strava.com by changing your password.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "This browser or app may not be secure" | You clicked "Sign in with Google". Enter your e-mail address in the Strava form instead (see [The one-time login](#the-one-time-login)). |
| "An unexpected error occurred" on the login page | Wait a moment and try again. Make sure you are in the window opened by strava-sync, not in a window controlled by another tool. |
| The program keeps waiting after the window was closed | The browser is still running in the background. Close it via its tray icon (Windows) or Cmd+Q (macOS). |
| "Still not logged in after the browser was closed" | Log in with e-mail, keep "Remember me" checked, and wait for the dashboard before closing the window. |
| `WinError 206` / "filename or extension is too long" while installing | Playwright contains deeply nested files and Windows limits paths to 260 characters. Clone into a short path such as `C:\strava-sync`, or [enable long paths](https://learn.microsoft.com/windows/win32/fileio/maximum-file-path-limitation#enable-long-paths-in-windows-10-version-1607-and-later). |
| "Neither Microsoft Edge nor Google Chrome was found" | Install one of them or set `browser.executable` in `config.json`. |
| "Could not start the browser in the background" | Close any strava-sync login window that is still open, then try again. |
| "Logged in as athlete X, but config.json expects Y" | Run `python main.py --relogin` and log in with the right account, or fix `strava.athlete_id`. |

## Limitations

- Only your own activities can be synced. The "My Activities" page is only available to the
  logged-in athlete.
- Activities you delete on Strava remain in the local database.
- The login needs a desktop with a browser, so strava-sync is not suited for headless servers.
  Copying `data/browser-profile` to another machine does not help: on Windows and macOS the
  browser encrypts its cookies per user account.
- Tested on Windows. macOS should work the same way; Linux is not supported yet.

## Development

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
ruff format strava_sync tests main.py
ruff check strava_sync tests main.py
mypy
pytest --cov=strava_sync
```

The tests use fakes for the browser and Strava and never touch the network.

```text
main.py            # entry point: version check, dependency bootstrap, CLI
strava_sync/
├── cli.py         # argument parsing and sync workflow
├── config.py      # config.json creation, loading and validation
├── browser.py     # browser discovery, one-time login, headless HTTP session
├── client.py      # training-log endpoints: paging, pacing, throttling
├── activity.py    # parsing of activity timestamps
├── storage.py     # SQLite persistence and CSV export
├── bootstrap.py   # installs missing dependencies on first start
└── exceptions.py  # user-facing error hierarchy
```

## License

[MIT](LICENSE). This project is not affiliated with or endorsed by Strava, Inc.

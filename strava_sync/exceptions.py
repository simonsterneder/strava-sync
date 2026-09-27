"""Exception hierarchy. Everything the CLI reports as a user-facing error derives from here."""


class StravaSyncError(Exception):
    """Base class for all expected, user-facing errors."""


class ConfigError(StravaSyncError):
    """The configuration file contains invalid values."""


class BrowserNotFoundError(StravaSyncError):
    """No supported browser (Microsoft Edge or Google Chrome) could be located."""


class LoginError(StravaSyncError):
    """The interactive login did not result in a Strava session."""


class SessionExpiredError(StravaSyncError):
    """Strava no longer accepts the stored login; the user has to log in again."""


class AthleteMismatchError(StravaSyncError):
    """The logged-in Strava account differs from the configured athlete id."""


class ApiError(StravaSyncError):
    """Strava returned an unexpected response."""


class ThrottledError(ApiError):
    """A single request was answered with HTTP 429; the caller may wait and retry."""


class RateLimitError(ApiError):
    """Strava keeps throttling requests; retrying now would not help."""


class StorageError(StravaSyncError):
    """The local database is unusable."""

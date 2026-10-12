"""NYT Games exceptions."""
import httpx


class NYTGamesError(Exception):
    """Base class for NYT Games errors."""


class NYTGamesHTTPError(NYTGamesError):
    """NYT returned an HTTP error.

    `status_code` is the HTTP status, and `response` is the `httpx.Response`,
    when there is one.
    """

    def __init__(self, message: str, status_code: int | None = None,
                 response: httpx.Response | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class NYTGamesAuthenticationError(NYTGamesHTTPError):
    """NYT rejected the request as unauthenticated (HTTP 401 or 403).

    Usually the NYT-S cookie is missing or has expired.
    """


class NYTGamesRateLimitError(NYTGamesHTTPError):
    """NYT is rate limiting requests (HTTP 429), even after retrying.

    `retry_after` is how many seconds NYT asked to wait, if it said.
    """

    def __init__(self, *args, retry_after: float | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


class NYTGamesNotFoundError(NYTGamesHTTPError):
    """NYT has no data for the request (HTTP 404), e.g. a date with no puzzle."""


class NYTGamesNoProfileError(NYTGamesError, KeyError):
    """The NYT account has no NYT Games profile, so there are no stats.

    NYT creates the profile when the account first plays a game while
    signed in. Subclasses KeyError, which was raised before.
    """

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


class NYTGamesParseError(NYTGamesError, ValueError):
    """An NYT page did not contain the expected game data."""


class NYTGamesExportError(NYTGamesError, ValueError):
    """A puzzle can't be converted to a file format.

    `reasons` lists what the format can't represent, for example squares
    labeled with text or clues that aren't straight across or down.
    """

    def __init__(self, fmt: str, reasons: list[str]):
        self.format = fmt
        self.reasons = reasons
        super().__init__(f"Can't export to {fmt}: " + "; ".join(reasons))

"""Shared state for nytg commands: the active profile, cookies and client."""
import datetime
import os
from dataclasses import dataclass
from dataclasses import field

import typer

from nytgames import NYTGamesClient
from nytgames.cli.config import Config
from nytgames.cli.dates import parse_date

COOKIES_ENV = "NYT_COOKIES"


@dataclass
class State:
    """Options from the root command, shared by every subcommand."""

    profile: str | None = None
    cookies: str | None = None
    config: Config = field(default_factory=Config)

    @property
    def active_profile(self) -> str:
        """The profile in use: --profile, then NYTG_PROFILE, then the active one."""
        return self.profile or os.environ.get("NYTG_PROFILE") or self.config.active_profile

    def resolve_cookies(self) -> tuple[str | None, str]:
        """Return the cookies to use and where they came from."""
        if self.cookies:
            return self.cookies, "--cookies"
        if os.environ.get(COOKIES_ENV):
            return os.environ[COOKIES_ENV], COOKIES_ENV
        cookies = self.config.get(self.active_profile, "cookies")
        if cookies:
            return cookies, f"profile {self.active_profile!r}"
        return None, "none"

    def client(self) -> NYTGamesClient:
        """Return a client using the resolved cookies."""
        return NYTGamesClient(cookies=self.resolve_cookies()[0])


state = State()


def date_arg(value: str, game: str | None = None) -> datetime.date:
    """Parse a date argument, reporting errors as a bad parameter."""
    try:
        return parse_date(value, game)
    except ValueError as err:
        raise typer.BadParameter(str(err)) from None

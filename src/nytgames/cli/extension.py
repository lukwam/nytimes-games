"""Public API for building command lines on top of nytg.

Requires the `cli` extra. Everything here is a stable, documented interface;
the other modules in ``nytgames.cli`` are internal and may change.

Example, a ``mytool`` command with every nytg command plus a ``db`` group::

    import typer
    from nytgames.cli.extension import FormatOption, create_app, emit, get_client, run

    app = create_app(name="mytool", help="My NYT tools.")
    db = typer.Typer(help="Query my archive.")
    app.add_typer(db, name="db")

    @db.command("wordle")
    def db_wordle(fmt: FormatOption = None) -> None:
        puzzle = get_client().wordle("2025-06-12")
        emit({"date": puzzle.print_date, "id": puzzle.id}, fmt)

    def main() -> None:
        run(app)

Commands get nytg's root options (--profile, --cookies, --format and
--version) and error handling for free.
"""
import datetime
from typing import Any

from nytgames import NYTGamesClient
from nytgames.cli.app import create_app
from nytgames.cli.app import run
from nytgames.cli.output import FormatOption
from nytgames.cli.output import TableRenderer
from nytgames.cli.output import console
from nytgames.cli.output import emit as _emit
from nytgames.cli.output import err_console
from nytgames.cli.output import key_value_table
from nytgames.cli.state import date_arg
from nytgames.cli.state import state

__all__ = [
    "FormatOption",
    "TableRenderer",
    "active_profile",
    "console",
    "create_app",
    "emit",
    "err_console",
    "get_client",
    "get_setting",
    "key_value_table",
    "parse_date",
    "resolve_cookies",
    "run",
]


def emit(data: Any, fmt: str | None = None, table: TableRenderer | None = None) -> None:
    """Print JSON-compatible data in the requested --format.

    ``fmt`` is the command's FormatOption value; None uses the root --format,
    then the profile's format setting, then a table. ``table`` is a function
    that takes ``data`` and yields Rich renderables for the table format;
    without one, dicts become key/value tables and lists become tables with
    one row per item.
    """
    _emit(data, fmt, table)


def get_client() -> NYTGamesClient:
    """Return an NYTGamesClient with the cookies nytg would use.

    Cookies come from --cookies, then NYT_COOKIES, then the active profile.
    """
    return state.client()


def resolve_cookies() -> tuple[str | None, str]:
    """Return the cookies nytg would use and where they came from."""
    return state.resolve_cookies()


def active_profile() -> str:
    """Return the profile in use: --profile, then NYTG_PROFILE, then the active one."""
    return state.active_profile


def get_setting(key: str) -> str | None:
    """Return a setting from the active profile's config.

    Extensions may store their own settings in the profile, using a prefix
    such as ``mytool.project``, with ``nytg config`` style tooling of their own.
    """
    return state.config.get(state.active_profile, key)


def parse_date(value: str, game: str | None = None) -> datetime.date:
    """Parse a date argument like nytg does: YYYY-MM-DD, today, yesterday,
    tomorrow, a weekday, or "first" for a game. Raises a usage error if invalid.
    """
    return date_arg(value, game)

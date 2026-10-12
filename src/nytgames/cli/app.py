"""nytg: the NYT Games command line.

``create_app()`` builds the command line and ``run()`` runs it with nytg's
error handling. Both are public through ``nytgames.cli.extension``, so other
tools can build their own command line on top of nytg's.
"""
import re
import sys
from typing import Annotated
from typing import Any
from typing import Optional

import requests
import typer
from rich.markup import escape

from nytgames import NYTGamesAuthenticationError
from nytgames import NYTGamesNoProfileError
from nytgames import NYTGamesNotFoundError
from nytgames import NYTGamesParseError
from nytgames import NYTGamesRateLimitError
from nytgames import __version__
from nytgames import parse_cookies
from nytgames.cli import archive
from nytgames.cli import bonus
from nytgames.cli import output
from nytgames.cli import player
from nytgames.cli import puzzles
from nytgames.cli import settings
from nytgames.cli.config import Config
from nytgames.cli.state import COOKIES_ENV
from nytgames.cli.state import state

DEFAULT_NAME = "nytg"
DEFAULT_HELP = """Puzzles, stats and archives from the New York Times Games.

Puzzles work without logging in. For your stats and progress, run
[bold]{name} auth login[/bold] with your NYT-S cookie, or set {env}.
"""


def create_app(
    name: str = DEFAULT_NAME,
    help: str | None = None,
    version: str | None = None,
    **typer_kwargs: Any,
) -> typer.Typer:
    """Return a new Typer app with every nytg command.

    Each call returns an independent app, so commands added to one don't
    affect another. ``name`` and ``help`` set the command name and its help,
    ``version`` is what ``--version`` prints (nytimes-games' version by
    default), and other keyword arguments are passed to ``typer.Typer``.

    The app has nytg's root options: --profile, --cookies, --format and
    --version. Run it with ``run(app)`` to get nytg's error messages.
    """
    settings_kwargs = {
        "name": name,
        "no_args_is_help": True,
        "rich_markup_mode": "rich",
        "pretty_exceptions_enable": False,
        "context_settings": {"help_option_names": ["-h", "--help"]},
    }
    settings_kwargs.update(typer_kwargs)
    app = typer.Typer(**settings_kwargs)
    help_text = help or DEFAULT_HELP.format(name=name, env=COOKIES_ENV)
    version_text = f"{name} {version or __version__}"

    def version_callback(value: bool) -> None:
        if value:
            typer.echo(version_text)
            raise typer.Exit()

    @app.callback(help=help_text)
    def root(
        profile: Annotated[
            Optional[str],
            typer.Option("--profile", "-p", envvar="NYTG_PROFILE", help="Profile to use for this command."),
        ] = None,
        cookies: Annotated[
            Optional[str],
            typer.Option("--cookies", help=f"NYT cookies for this command, e.g. NYT-S=... (or set {COOKIES_ENV}).",
                         show_default=False),
        ] = None,
        fmt: output.FormatOption = None,
        version: Annotated[
            bool, typer.Option("--version", callback=version_callback, is_eager=True, help="Show the version.")
        ] = False,
    ) -> None:
        state.config = Config()
        state.profile = profile
        state.cookies = cookies
        output.default_format = fmt or state.config.get(state.active_profile, "format")

    puzzles.register(app)
    bonus.register(app)
    player.register(app)
    app.command("archive")(archive.archive)
    app.add_typer(settings.build_auth_app(), name="auth")
    app.add_typer(settings.build_config_app(), name="config")
    return app


def cookie_values(raw: str | None) -> set[str]:
    """Return every cookie value that might appear in raw cookies, even malformed ones."""
    if not raw:
        return set()
    values = set(re.findall(r'"value"\s*:\s*"((?:[^"\\]|\\.)*)"', raw))
    for part in re.split(r"[;\n]", raw):
        values.add(part.partition("=")[2].strip())
    try:
        values.update(parse_cookies(raw).values())
    except ValueError:
        pass
    values.add(raw)
    return {value for value in values if len(value) >= 6}


def redact(text: str) -> str:
    """Remove the values of any cookies in use from an error message."""
    for value in sorted(cookie_values(state.resolve_cookies()[0]), key=len, reverse=True):
        text = text.replace(value, "…")
    return text


def run(app: typer.Typer) -> None:
    """Run an app, turning NYT errors into short messages and exit codes.

    Exits with 1 for NYT errors (rejected cookies, no puzzle, unreadable
    responses, failed requests), 2 for usage errors and 130 for Ctrl-C.
    """
    name = app.info.name or DEFAULT_NAME
    try:
        app()
    except NYTGamesAuthenticationError:
        output.err_console.print(
            "[red]NYT rejected the request.[/red] This needs your NYT cookies, which are missing "
            f"or have expired. Run [bold]{name} auth login[/bold] or set {COOKIES_ENV}."
        )
        sys.exit(1)
    except NYTGamesRateLimitError as err:
        wait = f" Try again in {err.retry_after:g} seconds." if err.retry_after else " Try again later."
        output.err_console.print(f"[red]NYT is rate limiting requests.[/red]{wait}")
        sys.exit(1)
    except NYTGamesNoProfileError:
        output.err_console.print("[red]No NYT Games profile yet.[/red] NYT creates one when this account "
                                 "first plays a game while signed in.")
        sys.exit(1)
    except NYTGamesNotFoundError:
        output.err_console.print("[red]Not found.[/red] NYT has no puzzle for that date.")
        sys.exit(1)
    except NYTGamesParseError as err:
        output.err_console.print(f"[red]Couldn't read NYT's response:[/red] {escape(redact(str(err)))}")
        sys.exit(1)
    except requests.RequestException as err:
        output.err_console.print(f"[red]Request to NYT failed:[/red] {escape(redact(str(err)))}")
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as err:  # noqa: BLE001 - never print a traceback that may contain cookies
        output.err_console.print(f"[red]Error:[/red] {type(err).__name__}: {escape(redact(str(err)))}",
                                 highlight=False)
        sys.exit(1)


app = create_app()


def main() -> None:
    """Run nytg."""
    run(app)


if __name__ == "__main__":
    main()

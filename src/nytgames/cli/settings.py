"""nytg auth and config commands."""
import json
from pathlib import Path
from typing import Annotated
from typing import Optional

import typer

from nytgames import NYTGamesAuthenticationError
from nytgames import NYTGamesClient
from nytgames import parse_cookies
from nytgames.cli.config import KEYS
from nytgames.cli.output import FormatOption
from nytgames.cli.output import console
from nytgames.cli.output import emit
from nytgames.cli.output import key_value_table
from nytgames.cli.state import COOKIES_ENV
from nytgames.cli.state import state


def mask(value: str) -> str:
    """Hide most of a cookie value, keeping the cookie name."""
    name, sep, secret = value.partition("=")
    if not sep:
        name, secret = "", value
    return f"{name}{sep}{secret[:6]}…" if len(secret) > 12 else f"{name}{sep}…"


def cookie_header(cookies: dict[str, str]) -> str:
    """Return cookies as a Cookie header string."""
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def login(
    cookie_file: Annotated[
        Optional[Path],
        typer.Option(
            "--from-file",
            help="Read cookies from a file: a Cookie-Editor JSON export or a Cookie header.",
            exists=True,
            dir_okay=False,
        ),
    ] = None,
    verify: Annotated[bool, typer.Option(help="Check the cookies with NYT before saving.")] = True,
) -> None:
    """Save your NYT cookies to the active profile.

    Copy the NYT-S cookie from a logged in nytimes.com browser session (your
    browser's developer tools, under the cookies for .nytimes.com) and paste
    it when prompted, as either the value or NYT-S=VALUE.
    """
    if cookie_file:
        text = cookie_file.read_text().strip()
        try:
            cookies = parse_cookies(json.loads(text))
        except json.JSONDecodeError:
            cookies = parse_cookies(text)
    else:
        text = typer.prompt("NYT-S cookie", hide_input=True).strip()
        cookies = parse_cookies(text if "=" in text else f"NYT-S={text}")
    if "NYT-S" not in cookies:
        raise typer.BadParameter("No NYT-S cookie found.")
    # NYT-S is the only cookie NYT needs; don't store the rest of the browser's cookies.
    cookies = {"NYT-S": cookies["NYT-S"]}

    profile = state.active_profile
    if verify:
        try:
            player = NYTGamesClient(cookies=cookies).player_stats()
        except NYTGamesAuthenticationError:
            console.print("[red]NYT rejected these cookies.[/red] Nothing was saved.")
            raise typer.Exit(1) from None
        console.print(f"Logged in as NYT user [bold]{player.user_id}[/bold].")
    state.config.set(profile, "cookies", cookie_header(cookies))
    console.print(f"Saved cookies to profile [bold]{profile}[/bold] in {state.config.path}")


def status(fmt: FormatOption = None) -> None:
    """Show which cookies are in use and whether NYT accepts them."""
    cookies, source = state.resolve_cookies()
    data = {"profile": state.active_profile, "cookies": source, "logged_in": False, "user_id": None}
    if cookies:
        try:
            player = state.client().player_stats()
            data.update(logged_in=True, user_id=player.user_id,
                        account_created=player.account_creation_date)
        except NYTGamesAuthenticationError:
            data["error"] = "NYT rejected the cookies; they may have expired"

    def table(data):
        status_text = "[green]logged in[/green]" if data["logged_in"] else "[red]not logged in[/red]"
        yield key_value_table({k: v for k, v in data.items() if k != "logged_in"}, title=status_text)

    emit(data, fmt, table)
    if not data["logged_in"]:
        raise typer.Exit(1)


def logout() -> None:
    """Remove the saved cookies from the active profile."""
    profile = state.active_profile
    if state.config.unset(profile, "cookies"):
        console.print(f"Removed cookies from profile [bold]{profile}[/bold].")
    else:
        console.print(f"Profile [bold]{profile}[/bold] has no saved cookies.")


def check_key(key: str) -> str:
    if key not in KEYS:
        raise typer.BadParameter(f"Unknown setting {key!r}. Settings: {', '.join(KEYS)}.")
    return key


def config_list(fmt: FormatOption = None) -> None:
    """Show the settings in the active profile."""
    profile = state.active_profile
    data = {"profile": profile, **state.config.items(profile)}
    if "cookies" in data:
        data["cookies"] = mask(data["cookies"])
    emit(data, fmt, lambda d: [key_value_table(d)])


def config_get(key: Annotated[str, typer.Argument(help=", ".join(KEYS))]) -> None:
    """Print one setting from the active profile."""
    value = state.config.get(state.active_profile, check_key(key))
    if value is None:
        raise typer.Exit(1)
    typer.echo(value)


def config_set(
    key: Annotated[str, typer.Argument(help=", ".join(KEYS))],
    value: Annotated[Optional[str], typer.Argument(help="Prompted for (hidden) if omitted.")] = None,
) -> None:
    """Save a setting to the active profile."""
    check_key(key)
    if value is None:
        value = typer.prompt(key, hide_input=key == "cookies")
    state.config.set(state.active_profile, key, value)
    console.print(f"Set [cyan]{key}[/cyan] in profile [bold]{state.active_profile}[/bold].")


def config_unset(key: Annotated[str, typer.Argument(help=", ".join(KEYS))]) -> None:
    """Remove a setting from the active profile."""
    if not state.config.unset(state.active_profile, check_key(key)):
        console.print(f"[cyan]{key}[/cyan] isn't set in profile [bold]{state.active_profile}[/bold].")


def config_path() -> None:
    """Print the path of the config file."""
    typer.echo(state.config.path)


def profiles_list(fmt: FormatOption = None) -> None:
    """List profiles and show which one is active."""
    active = state.active_profile
    names = sorted(set(state.config.profiles()) | {active})
    data = [
        {"name": name, "active": name == active, "cookies": bool(state.config.get(name, "cookies"))}
        for name in names
    ]

    def table(data):
        from rich.table import Table

        t = Table(header_style="bold")
        t.add_column("")
        t.add_column("Profile")
        t.add_column("Cookies")
        for row in data:
            t.add_row("*" if row["active"] else "", row["name"], "yes" if row["cookies"] else "")
        yield t

    emit(data, fmt, table)


def profiles_activate(name: str) -> None:
    """Make a profile the default for future commands."""
    state.config.activate(name)
    console.print(f"Activated profile [bold]{name}[/bold].")


def profiles_delete(name: str) -> None:
    """Delete a profile and its settings."""
    if not state.config.delete_profile(name):
        console.print(f"No profile named [bold]{name}[/bold].")
        raise typer.Exit(1)
    console.print(f"Deleted profile [bold]{name}[/bold].")


def build_auth_app() -> typer.Typer:
    """Return a new `auth` command group."""
    app = typer.Typer(help=f"Log in with your NYT cookies (or set {COOKIES_ENV}) and check them.", no_args_is_help=True)
    app.command("login")(login)
    app.command("status")(status)
    app.command("logout")(logout)
    return app


def build_config_app() -> typer.Typer:
    """Return a new `config` command group, with its `profiles` subgroup."""
    app = typer.Typer(help="View and change settings.", no_args_is_help=True)
    app.command("list")(config_list)
    app.command("get")(config_get)
    app.command("set")(config_set)
    app.command("unset")(config_unset)
    app.command("path")(config_path)
    profiles = typer.Typer(help="Manage named profiles, such as one per NYT account.", no_args_is_help=True)
    profiles.command("list")(profiles_list)
    profiles.command("activate")(profiles_activate)
    profiles.command("delete")(profiles_delete)
    app.add_typer(profiles, name="profiles")
    return app

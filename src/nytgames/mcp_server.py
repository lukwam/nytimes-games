"""nytg-mcp: an MCP server for the NYT Games, for coding agents and other MCP clients.

Requires the `mcp` extra::

    pip install "nytimes-games[mcp]"
    claude mcp add nytimes-games -- nytg-mcp

Runs locally over stdio. Cookies come from NYT_COOKIES or your nytg profile
(``nytg auth login``), the same as nytg; they are never returned or logged.
Every tool is read-only except ``export_crossword``, which writes a file.
"""
import datetime
import functools
import logging
import os
from pathlib import Path
from typing import Any
from typing import Literal

from nytgames import NYTGamesAuthenticationError
from nytgames import NYTGamesClient
from nytgames import NYTGamesExportError
from nytgames import NYTGamesHTTPError
from nytgames import NYTGamesNoProfileError
from nytgames import NYTGamesNotFoundError
from nytgames import NYTGamesRateLimitError
from nytgames import __version__
from nytgames import formats
from nytgames import views
from nytgames.cli import dates
from nytgames.cli.config import Config
from nytgames.cli.dates import parse_date
from nytgames.client import BADGE_GAMES
from nytgames.files import write_file

try:
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp_types import ToolAnnotations
except ImportError as err:  # pragma: no cover
    raise ImportError('nytg-mcp needs the mcp extra. Install it with: pip install "nytimes-games[mcp]"',
                      name=err.name) from err

INSTRUCTIONS = """\
Tools for the New York Times Games: Wordle, Connections, Strands, Spelling
Bee, Letter Boxed and the Daily, Mini, Midi and Bonus crosswords, plus the
user's own stats, progress, badges and WordleBot analysis.

Dates are YYYY-MM-DD, "today", "yesterday", "tomorrow" or a weekday name.

Spoilers: puzzle tools hide answers unless include_answers is true. Leave it
false when the user is still solving (for example when they ask for a hint),
and set it to true only when they want the answers or analysis that needs them.

The user's own data (stats, today, histories, wordlebot, badges, saved progress)
needs their NYT cookie. If a tool says cookies are missing or expired, tell
the user to run `nytg auth login` or set NYT_COOKIES.
"""

CrosswordType = Literal["daily", "mini", "midi", "bonus"]
READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
# Destructive: with overwrite, it replaces an existing file.
WRITES_FILE = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=True)

server = MCPServer(name="nytimes-games", version=__version__, instructions=INSTRUCTIONS)
# The client logs every request at INFO; keep the server's log to warnings and errors.
logging.getLogger("nytgames").setLevel(logging.WARNING)


def client() -> NYTGamesClient:
    """Return a client with the cookies nytg would use: NYT_COOKIES, then the profile."""
    cookies = os.environ.get("NYT_COOKIES")
    if not cookies:
        config = Config()
        profile = os.environ.get("NYTG_PROFILE") or config.active_profile
        cookies = config.get(profile, "cookies")
    return NYTGamesClient(cookies=cookies)


def day(value: str, game: str | None = None) -> datetime.date:
    try:
        return parse_date(value, game)
    except ValueError as err:
        raise ToolError(str(err)) from None


def nyt_errors(fn):
    """Turn NYT errors into tool errors with messages an agent can act on."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except NYTGamesAuthenticationError:
            raise ToolError("NYT rejected the request: this needs the user's NYT cookies, which are missing "
                            "or have expired. They can run `nytg auth login` or set NYT_COOKIES.") from None
        except NYTGamesNoProfileError:
            raise ToolError("The user's NYT account has no NYT Games profile, so there are no stats yet. NYT "
                            "creates one when they first play a game while signed in.") from None
        except NYTGamesNotFoundError:
            raise ToolError("Not found: NYT has nothing for that date or ID.") from None
        except NYTGamesRateLimitError as err:
            wait = f" Try again in {err.retry_after:g} seconds." if err.retry_after else " Try again later."
            raise ToolError("NYT is rate limiting requests." + wait) from None
        except NYTGamesExportError as err:
            raise ToolError(f"This crossword can't be saved as {err.format}: " + "; ".join(err.reasons)) from None
        except NYTGamesHTTPError as err:
            status = err.response.status_code if err.response is not None else "unknown"
            raise ToolError(f"NYT returned an error (HTTP {status}).") from None
        except ValueError as err:
            # Cookie and date errors; their messages never include cookie values.
            raise ToolError(str(err)) from None
    return wrapper


def tool(annotations: ToolAnnotations = READ_ONLY):
    def decorator(fn):
        return server.tool(annotations=annotations)(nyt_errors(fn))
    return decorator


# Puzzles


@tool()
def wordle(date: str = "today", include_answers: bool = False) -> dict[str, Any]:
    """Get a Wordle puzzle (from 2021-06-19). The solution is only included with include_answers."""
    return views.wordle_view(client().wordle(day(date, "wordle").isoformat()), include_answers)


@tool()
def connections(date: str = "today", include_answers: bool = False) -> dict[str, Any]:
    """Get a Connections puzzle (from 2023-06-12): the 16 cards as a 4x4 board.

    The groups (categories and their cards) are only included with include_answers.
    """
    return views.connections_view(client().connections(day(date, "connections").isoformat()), include_answers)


@tool()
def strands(date: str = "today", include_answers: bool = False) -> dict[str, Any]:
    """Get a Strands puzzle (from 2024-03-04): the theme clue and letter board.

    The spangram, theme words and their board coordinates are only included with include_answers.
    """
    return views.strands_view(client().strands(day(date, "strands").isoformat()), include_answers)


@tool()
def bonus_week(date: str = "today") -> dict[str, Any]:
    """List the weekly Bonus Puzzles drop that includes a date (drops come out on Wednesdays from
    2026-08-26): Wordle in 1, Connections 3x3, Colorful Strands and bonus crosswords, with titles,
    bylines, IDs and slugs.
    """
    return views.bonus_week_view(client().bonus_week(day(date).isoformat()))


@tool()
def bonus_puzzle(
    game: Literal["wordle-in-one", "connections", "strands", "mini", "easy", "special"],
    date: str = "today",
    include_answers: bool = False,
) -> dict[str, Any]:
    """Get a puzzle from the week's Bonus Puzzles drop that includes a date. Wordle in 1 has five
    rounds, each a starting guess and one word to find; Connections 3x3 has 3 groups of 3;
    Colorful Strands is a Strands board; crosswords have a grid and clues.

    game is mini (the Mystery Mini), easy (Easy Mode Crossword) or special (Special Crossword) for
    crosswords. Solutions, groups, theme words and crossword answers are only included with include_answers.
    """
    nyt = client()
    week = nyt.bonus_week(day(date).isoformat())
    listing = views.find_bonus_listing(week, game)
    if listing is None:
        raise ToolError(f"No {game} puzzle in the week of {week.drop_date}")
    return views.bonus_puzzle_view(listing, nyt.bonus_puzzle(listing), include_answers)


@tool()
def spelling_bee(date: str = "today", include_answers: bool = False, include_hints: bool = True) -> dict[str, Any]:
    """Get a Spelling Bee puzzle (from 2018-05-06): letters, word and pangram counts, and points.

    include_hints adds Spelling Bee Forum style hints (words by first letter and length, two-letter
    starts), which don't reveal words. The answers are only included with include_answers.
    """
    puzzle = client().spelling_bee_puzzle(day(date, "spelling-bee").isoformat())
    return views.bee_view(puzzle, include_answers, include_hints)


@tool()
def letter_boxed(date: str = "today", include_answers: bool = False) -> dict[str, Any]:
    """Get a Letter Boxed puzzle (from 2018-12-17): the four sides and par.

    NYT's solution and the full list of accepted words are only included with include_answers.
    """
    return views.letter_boxed_view(client().letter_boxed(day(date, "letter-boxed").isoformat()),
                                   include_answers)


@tool()
def crossword(
    type: CrosswordType = "daily",
    date: str = "today",
    puzzle_id: int | None = None,
    include_answers: bool = False,
) -> dict[str, Any]:
    """Get a crossword: its grid ("#" is a block) and every entry with its clue, length, starting
    (row, col), crossing entries and referenced clues.

    Daily puzzles go back to 1993-11-21, Minis to 2014-08-21, Midis to 2026-02-25, and Bonus
    puzzles to 1997 (the 1st of each month). Use puzzle_id instead of date for dates with two
    puzzles (see puzzle_archive). Answers, and letters in the grid, are only included with
    include_answers.
    """
    nyt = client()
    puzzle = (nyt.crossword_by_id(puzzle_id) if puzzle_id is not None
              else nyt.crossword(type, day(date, f"crossword-{type}").isoformat()))
    return views.crossword_view(puzzle, type, include_answers, clues=False, entries=True)


@tool()
def wordlebot_summary(date: str = "today", include_answers: bool = False) -> dict[str, Any]:
    """Get WordleBot's summary of how everyone did on a day's Wordle (from 2021-06-19): players,
    average guesses, skill and luck (0-1) and the share solving in three or fewer, in normal mode.

    The bot's own solve paths (which include the solution) are only included with include_answers.
    """
    when = day(date, "wordle")
    nyt = client()
    puzzle = nyt.wordle(when.isoformat())
    summary = nyt.wordlebot_summary(when.isoformat(), solution=puzzle.solution)
    return views.wordlebot_view(when, puzzle, summary, None, include_answers)


@tool()
def puzzle_archive(
    game: Literal["wordle", "connections", "strands", "crossword_daily", "crossword_mini", "crossword_midi"],
    date_start: str,
    date_end: str = "today",
) -> list[dict[str, Any]]:
    """List the puzzles published between two dates, with their IDs, print dates and bylines.

    Some dates have two crosswords (such as 2022-12-31); get each with crossword(puzzle_id=...).
    """
    start, end = day(date_start, game.replace("_", "-")), day(date_end)
    return [{"id": p.id, "print_date": p.print_date, "byline": p.byline, "editor": p.editor}
            for p in client().archive(game, start.isoformat(), end.isoformat())]


# The user's own data


@tool()
def stats() -> dict[str, Any]:
    """Get the user's stats for every game: a summary (played, won, win rate, streaks) and the
    full details, such as the Wordle guess distribution and crossword times by weekday. Needs cookies.
    """
    player = client().player_stats()
    return {"summary": views.summary_rows(player.stats),
            "details": player.stats.model_dump(mode="json", by_alias=True, exclude_none=True)}


@tool()
def today() -> list[dict[str, Any]]:
    """Get which of today's games the user has played: status and details such as solve times. Needs cookies."""
    return views.today_rows(client(), dates.today())


def window(date_start: str | None, date_end: str | None, game: str) -> tuple[datetime.date, datetime.date]:
    last = day(date_end, game) if date_end else dates.today()
    first = day(date_start, game) if date_start else last - datetime.timedelta(days=29)
    if first > last:
        raise ToolError("date_start is after date_end")
    return first, last


@tool()
def crossword_history(
    type: CrosswordType = "daily", date_start: str | None = None, date_end: str | None = None,
) -> list[dict[str, Any]]:
    """Get the user's crossword results for a date range (default: the last 30 days): solved,
    percent filled, solve time in seconds, gold star and whether help was used. Needs cookies.
    """
    first, last = window(date_start, date_end, f"crossword-{type}")
    return views.crossword_results(client(), type, first, last)


@tool()
def wordle_history(date_start: str | None = None, date_end: str | None = None) -> list[dict[str, Any]]:
    """Get the user's Wordle results for a date range (default: the last 30 days): won or lost,
    number of guesses and their guesses. Needs cookies.
    """
    first, last = window(date_start, date_end, "wordle")
    return views.wordle_results(client(), first, last)


@tool()
def spelling_bee_history(date_start: str | None = None, date_end: str | None = None) -> list[dict[str, Any]]:
    """Get the user's Spelling Bee results for a date range (default: the last 30 days): rank and
    words and pangrams found. Needs cookies; fetches one puzzle per day, so keep ranges short.
    """
    first, last = window(date_start, date_end, "spelling-bee")
    return views.bee_results(client(), first, last)


@tool()
def bonus_history(date_start: str | None = None, date_end: str | None = None) -> list[dict[str, Any]]:
    """Get the user's results for each weekly Bonus Puzzle in a date range (default: the last 30
    days): solved, in progress or not played, with details such as rounds solved, mistakes or
    solve time. Needs cookies.
    """
    first, last = window(date_start, date_end, "bonus")
    return views.bonus_results(client(), first, last)


@tool()
def wordlebot() -> dict[str, Any]:
    """Get the user's WordleBot analysis of today's Wordle compared with everyone: skill and luck
    (0-1) overall and by round, their guesses and where their skill falls among players.

    Needs cookies. NYT keeps only today's game, and only after the user opens WordleBot; until
    then "you" is missing. For other days use wordlebot_summary.
    """
    nyt = client()
    when = dates.today()
    puzzle = nyt.wordle(when.isoformat())
    summary = nyt.wordlebot_summary(when.isoformat(), solution=puzzle.solution)
    return views.wordlebot_view(when, puzzle, summary, nyt.wordlebot(), answers=False)


@tool()
def badges(game: Literal["wordle", "connections", "strands", "spelling_bee"] | None = None) -> list[dict[str, Any]]:
    """Get the user's badges for one game or all four, earned or not: name, description, level,
    next level, progress, when last earned and artwork URL. Needs cookies.
    """
    games = {"wordle": "wordleV2"}.get(game, game) if game else None
    return views.badge_rows(client().badges([games] if games else BADGE_GAMES))


# Files


@tool(WRITES_FILE)
def export_crossword(
    path: str,
    type: CrosswordType = "daily",
    date: str = "today",
    puzzle_id: int | None = None,
    include_progress: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Save a crossword as a file for other crossword apps. The format comes from the path's
    extension: .puz (Across Lite), .ipuz or .xml (Crossword Compiler).

    include_progress adds the user's saved fill and timer (needs cookies). Returns the path and
    notes on anything the format approximates, such as shading shown as circles in .puz. Some
    special puzzles can't be saved in these formats; the error says why. Files are for personal use.
    """
    target = Path(path).expanduser()
    fmt = target.suffix.lower().lstrip(".")
    if fmt not in formats.FORMATS:
        raise ToolError("Use a path ending in .puz, .ipuz or .xml")
    if target.exists() and not overwrite:
        raise ToolError(f"{target} already exists; set overwrite to replace it")
    nyt = client()
    puzzle = (nyt.crossword_by_id(puzzle_id) if puzzle_id is not None
              else nyt.crossword(type, day(date, f"crossword-{type}").isoformat()))
    game = nyt.crossword_game(puzzle.id, type) if include_progress else None
    data = formats.export(puzzle, fmt, game, title=views.export_title(puzzle, type))
    try:
        write_file(target, data, overwrite)
    except FileExistsError:
        # Checked again here: the file may have been created while the puzzle was fetched.
        raise ToolError(f"{target} already exists; set overwrite to replace it") from None
    return {"path": str(target.resolve()), "format": fmt, "bytes": len(data), "puzzle_id": puzzle.id,
            "date": puzzle.publicationDate, "notes": formats.fidelity(puzzle, fmt, game)}


def main() -> None:
    """Run the MCP server over stdio."""
    server.run("stdio")


if __name__ == "__main__":
    main()

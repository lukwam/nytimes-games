# nytimes-games

[![PyPI](https://img.shields.io/pypi/v/nytimes-games)](https://pypi.org/project/nytimes-games/)
[![Python](https://img.shields.io/pypi/pyversions/nytimes-games)](https://pypi.org/project/nytimes-games/)
[![Test](https://github.com/lukwam/nytimes-games/actions/workflows/test.yml/badge.svg)](https://github.com/lukwam/nytimes-games/actions/workflows/test.yml)
[![Coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Flukwam%2Fnytimes-games%2Fbadges%2Fcoverage-badge.json)](https://github.com/lukwam/nytimes-games/actions/workflows/test.yml)
[![NYT live check](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Flukwam%2Fnytimes-games%2Fbadges%2Flive-check.json)](https://github.com/lukwam/nytimes-games/actions/workflows/live.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](https://github.com/lukwam/nytimes-games/blob/main/LICENSE)

An unofficial Python client for the New York Times Games APIs: Wordle,
Connections, Strands, Spelling Bee, Letter Boxed and the Daily, Mini, Midi and
Bonus crosswords, plus your own stats and game progress.

NYT doesn't publish documentation or an API spec for these endpoints. This
package wraps them in one client with typed, validated
[Pydantic](https://docs.pydantic.dev/) models, so you can build archives,
stats dashboards, bots or your own games without reverse engineering NYT's
APIs first. Optional extras add the `nytg` command line tool, an MCP server
for AI agents, and a REST API.

![nytg showing a Connections puzzle, a Strands board, a Mini crossword and Spelling Bee hints](https://raw.githubusercontent.com/lukwam/nytimes-games/main/docs/screenshot.svg)

## Installation

```bash
pip install nytimes-games
```

The package installs as `nytimes-games` and is imported as `nytgames`.
Python 3.10 or newer is required.

## Quick start

```python
from nytgames import NYTGamesClient

client = NYTGamesClient()

client.wordle("2025-06-12").solution
client.connections("2025-06-12").categories
client.crossword("mini")                  # today's Mini
client.crossword("daily", "1993-11-21")   # any Daily back to 1993
```

Your stats and game progress need your NYT session cookie:

```python
client = NYTGamesClient(cookies="NYT-S=...")

stats = client.player_stats().stats
stats.wordle.calculatedStats.currentStreak
stats.connections.puzzles_won
stats.crossword_daily.dailyStats["monday"].avgTimeSeconds
```

## What's available

Puzzles don't need cookies. Everything about you does.

### Puzzles

| Game | Method | Available from | What you get | Spoilers |
|---|---|---|---|---|
| Wordle | `wordle(date)` | 2021-06-19 | Puzzle number, editor | `solution` |
| Connections | `connections(date)` | 2023-06-12 | The 16 cards (words or pictures) and starting board | `categories` (the groups) |
| Strands | `strands(date)` | 2024-03-04 | Theme clue and letter board | `spangram`, `themeWords`, word paths |
| Spelling Bee | `spelling_bee_puzzle(date)` | 2018-05-06 | Letters, word and pangram counts, forum-style hints | `answers`, `pangrams` |
| Letter Boxed | `letter_boxed(date)` | 2018-12-17 | Sides, par, every accepted word | `ourSolution` |
| Crossword | `crossword(publish_type, date=None)` | Daily 1993-11-21, Mini 2014-08-21, Midi 2026-02-25, Bonus 1997 | Grid, clues, entries, rebus, circles and shading | cell `answer`s |
| Crossword by ID | `crossword_by_id(puzzle_id)` | Any crossword, e.g. both puzzles on a date with two | Same as `crossword` | cell `answer`s |
| Crossword schedule | `crossword_oracle(publish_type)` | Current and next puzzle | Puzzle IDs and publish times | |
| WordleBot summary | `wordlebot_summary(date)` | 2021-06-19 | How everyone did: average guesses, skill and luck by mode, guess distributions, skill percentiles | `guesses` (the bot's solve paths) |
| Bonus Puzzles | `bonus_week(date)`, `bonus_weeks(date_start, date_end)`, `bonus_puzzle(listing)` | 2026-08-26 | Each Wednesday's drop: Wordle in 1, Connections 3x3, Colorful Strands and bonus crosswords (Mystery Mini, Easy Mode, Special), with titles, bylines, IDs and slugs | Wordle in 1 `solution`s, and as for each game |
| Puzzle list | `archive(game, date_start, date_end)` | Wordle, Connections, Strands, Daily, Mini, Midi | Puzzle IDs and dates for a range | Wordle `solution` |

### You (needs your NYT-S cookie)

| Data | Method | What you get |
|---|---|---|
| Stats | `player_stats()` | Streaks, win rates and distributions for every game you've played |
| Crossword progress | `crossword_game(puzzle_ids, publish_type)` | Your filled squares, time, gold star, revealed and checked squares (up to 30 puzzles per call) |
| Crossword list | `crossword_puzzles(publish_type, date_start=..., date_end=...)` | Daily, Mini and Bonus puzzles with your solved status and star (90 days or less per call) |
| Wordle progress | `wordle_latest(puzzle_ids)` | Your guesses and result |
| Connections progress | `connections_latest(puzzle_ids)` | Your guesses, mistakes and solved groups, and whether you won (up to 30 puzzles per call) |
| Strands progress | `strands_latest(puzzle_ids)` | Your found words, other words and whether you solved it (up to 30 puzzles per call) |
| WordleBot | `wordlebot()` | Your luck and skill for today's Wordle, overall and by round (today only, after you've opened WordleBot) |
| Spelling Bee progress | `spelling_bee_latest(puzzle_ids)` | Words you found and your rank (up to 30 puzzles per call) |
| Bonus Puzzles progress | `wordle_in_one_latest(puzzle_ids)`, `connections_latest(puzzle_ids, bonus=True)`, `strands_latest(puzzle_ids, bonus=True)`, `crossword_game(puzzle_ids, "bonus")` | Your saved bonus games, by the `id` in a week's listing |
| Badges | `badges(games)`, `trophy_case(game)` | Every Wordle, Connections, Strands and Spelling Bee badge, earned or not, with your level and progress. Each badge's `info` has its name, description and artwork |

The `*_latest()` results also include `badges_trophy_shelf`, the three badges
NYT features for that game. Badge names, descriptions and artwork come from a
copy of the games app's own table in `nytgames.badges` (`badge_info(id)`,
`all_badges()`), since NYT doesn't serve them from an API:

```python
for game, trophies in client.badges().trophies.items():
    for badge in trophies.badges:
        info = badge.info
        print(game, badge.name, badge.progress, badge.next_level,
              info.image_url(badge.level or badge.next_level, earned=badge.is_earned) if info else "")
```

NYT doesn't record individual solve events, so progress means your saved
game: the current state and totals, not a history of each move.

Dates are `YYYY-MM-DD` strings. `publish_type` is `daily`, `mini`, `midi` or
`bonus`, and `date=None` returns today's puzzle. NYT usually serves the next
day's puzzle a day early.

`archive()` is the quickest way to get puzzle IDs for a date range, for
example to check your progress on a month of puzzles:

```python
midis = client.archive("crossword_midi", "2026-09-01", "2026-09-30")
client.crossword_game([p.id for p in midis], "midi")   # up to 30 IDs per call
```

### Read-only

The library never writes anything to NYT. Every request it makes is a GET,
so it can't change your saved games, stats or streaks. The test suite checks
that every request is a GET.

### Puzzle structure

The models include helpers for working with a puzzle's structure, for
crossword research, trainers or solvers:

```python
puzzle = client.crossword("daily", "2025-06-12")

for entry in puzzle.entries():
    entry.id            # "50-Across"
    entry.clue          # "Major basketball feat … or a feature shared by 3-, 6- and 9-Down"
    entry.answer        # "QUADRUPLEDOUBLE", with rebus squares' full answers
    entry.coordinates   # ((11, 0), (11, 1), …): (row, col) of each square
    entry.crossings     # ("50-Down", "51-Down", …)
    entry.references    # ("9-Down", "3-Down", "6-Down")
    entry.rebus         # True if the answer is longer than its squares

puzzle.squares()        # every square: answer, label, rebus, circled, shaded

client.strands(date).words()          # theme words and spangram with their paths
client.connections(date).board()      # the 4x4 starting board
```

Special puzzles are kept as they are: text square labels, extra clue lists
such as "Around" (entry IDs like `Around-1`), and entries that turn corners.

### Crossword files

Export crosswords to the standard formats other crossword apps use, with your
saved progress if you like:

```python
from nytgames import formats

puzzle = client.crossword("daily", "2025-06-12")
game = client.crossword_game(puzzle.id, "daily")      # optional: your progress

open("daily.puz", "wb").write(formats.to_puz(puzzle, game))     # Across Lite
formats.to_ipuz(puzzle, game)                                    # ipuz, as a dict
open("daily.xml", "w").write(formats.to_xml(puzzle, game))      # Crossword Compiler XML
formats.export(puzzle, "ipuz")                                   # any format, as bytes
```

| Format | Notes |
|---|---|
| `.puz` | Across Lite, the most widely supported. Rebus squares, circles, your fill, revealed squares and the timer. Shaded squares are shown as circles, and text must fit Latin-1 (typographic quotes and dashes are converted) |
| `.ipuz` | The open [ipuz](http://ipuz.org) JSON format. Rebus, circles, shading and your fill |
| `.xml` | [Crossword Compiler](https://crossword.info/xml/rectangular-puzzle.xsd) rectangular-puzzle XML. Rebus, circles, shading, your fill and revealed or penciled squares |

A few special puzzles use gimmicks these formats can't represent, such as
squares labeled with text or clues that wind around the grid. Exporting them
raises `NYTGamesExportError`, whose `reasons` say why; `export_problems(puzzle,
fmt)` returns the reasons without exporting. `fidelity(puzzle, fmt)` lists
what an export approximates, such as italics in clues or shading shown as
circles in `.puz`. Exported files are for personal
use: the puzzles are copyrighted by The New York Times.

Spelling Bee extras:

```python
from nytgames import spelling_bee_hints

puzzle = client.spelling_bee_puzzle("2026-10-03")
spelling_bee_hints(puzzle)      # Spelling Bee Forum style hints: counts, pairs, points
client.spelling_bee_puzzles()   # every puzzle on the game page (about two weeks)
```

## Cookies

To get your `NYT-S` cookie, log in at nytimes.com, open your browser's
developer tools, and find the `NYT-S` cookie for `.nytimes.com` (Application
tab in Chrome, Storage tab in Firefox). Treat it like a password: it gives
access to your NYT account.

`cookies` can be:

- a `Cookie` header string: `"NYT-S=...; nyt-a=..."`
- a dict: `{"NYT-S": "..."}`
- a list of cookie objects with `name` and `value` keys, such as a JSON export
  from the Cookie-Editor browser extension
- either of those as a JSON string, so `NYT_COOKIES="$(cat cookies.json)"`
  works with an export file

Cookies that can't be sent (for example with line breaks in a value) raise
`ValueError` before any request is made, and error messages never include
cookie values.

## Errors

HTTP errors from NYT are raised as `NYTGamesHTTPError`, with the HTTP status
as `.status_code` and the `httpx.Response` as `.response`:

| Exception | When |
|---|---|
| `NYTGamesAuthenticationError` | 401 or 403, usually a missing or expired `NYT-S` cookie |
| `NYTGamesNotFoundError` | 404, for example a date with no puzzle |
| `NYTGamesRateLimitError` | 429 after retrying; `retry_after` has NYT's suggested wait, if any |
| `NYTGamesHTTPError` | any other HTTP error |
| `NYTGamesParseError` | an NYT page didn't contain the expected game data (a `ValueError`) |

```python
from nytgames import NYTGamesNotFoundError

try:
    client.wordle("1900-01-01")
except NYTGamesNotFoundError:
    print("No puzzle that day")
```

### Network behavior

Failed connections, timeouts, rate limits (429) and NYT server errors are
retried up to 3 times with exponential backoff, honoring NYT's `Retry-After`
header. Adjust with `NYTGamesClient(retries=5, backoff=1.0, timeout=60)`, or
turn retries off with `retries=0`.

You can pass your own `httpx.Client` (or `httpx.AsyncClient` for the async
client) as `http_client`, for example to add caching or a proxy. The client
doesn't close it, and still retries as above.

Cookies are sent only to NYT (or the `base_url` you set) and are never logged.

## Models

Every method returns Pydantic models from `nytgames.models`. Fields NYT adds
later are kept rather than rejected, so new NYT fields don't break your code.
Use `.model_dump()` to get plain dicts, and `by_alias=True` to keep NYT's
original keys, such as `"Queen Bee"` in the Spelling Bee ranks.

## Examples

[`examples/`](examples) has small projects built on the package: an
alternative [Letter Boxed solver](examples/letter_boxed_solver.py) using the
day's accepted words, [clue reuse](examples/clue_reuse.py) across recent
crosswords, your [solve times](examples/solve_times.py) by weekday and
constructor, and [your own REST API](examples/api) in Docker.

## Async apps

`AsyncNYTGamesClient` has every method of `NYTGamesClient`, awaited. Both use
[httpx](https://www.python-httpx.org/), so there's no extra to install:

```python
import asyncio
from nytgames import AsyncNYTGamesClient


async def main():
    async with AsyncNYTGamesClient(cookies="NYT-S=...") as client:
        wordle = await client.wordle("2026-10-11")
        stats = await client.player_stats()
        # Fetch several at once; keep it modest to be polite to NYT.
        week = await asyncio.gather(*(client.connections(f"2026-10-0{d}") for d in range(1, 8)))


asyncio.run(main())
```

Errors, retries and cookie handling are the same as the sync client's. Pass
your own `httpx.AsyncClient` as `http_client` to control transport details;
it isn't closed when the client is. Both clients
run the same code for every endpoint, so they always have the same methods.

**FastAPI:** use `AsyncNYTGamesClient` in `async def` routes, or the sync
client in plain `def` routes (FastAPI runs those in a thread pool). The
routes in `nytgames.api` use the sync client this way.

**Home Assistant:** use `AsyncNYTGamesClient` with Home Assistant's shared
httpx client (`get_async_client(hass)`) as `http_client`.

## Command line

The optional `cli` extra installs `nytg`:

```bash
pipx install "nytimes-games[cli]"     # or: pip install "nytimes-games[cli]"
```

```bash
nytg wordle                      # today's Wordle, without the answer
nytg wordle yesterday --answers
nytg connections friday -a       # the groups, in their colors
nytg strands 2025-06-12
nytg bee --hints                 # Spelling Bee Forum style hints
nytg letter-boxed
nytg crossword mini              # the grid and clues
nytg crossword daily 1993-11-21 --answers
nytg crossword mini --save mini.puz     # or .ipuz, or .xml (Crossword Compiler)
nytg crossword daily yesterday --save daily.ipuz --progress   # with your progress
nytg bonus week                  # this week's Bonus Puzzles (any day in the week works)
nytg bonus wordle-in-one         # each round's starting guess
nytg bonus connections -a        # Connections 3x3
nytg bonus strands 2026-09-30
nytg bonus crossword mini        # or easy, or special; --save works here too
```

Answers are hidden unless you pass `--answers`, in every output format.
Dates can be `YYYY-MM-DD`, `today`, `yesterday`, `tomorrow` or a weekday, and
`first` for the first puzzle in `nytg archive`.

### Your stats and history

Log in once with your `NYT-S` cookie (see [Cookies](#cookies)):

```bash
nytg auth login                  # paste the cookie; it's checked, then saved
nytg auth status
```

```bash
nytg stats                       # every game at a glance
nytg stats crossword             # averages, bests and streaks by weekday
nytg today                       # which of today's games you've played
nytg wordlebot                   # your WordleBot luck and skill vs. everyone (any date for everyone)
nytg history crossword --from 2026-01-01 -f csv > solves.csv
nytg history wordle --from monday
nytg history connections         # won or lost, mistakes and groups found
nytg history strands
nytg history bee
nytg history bonus               # the weekly Bonus Puzzles you've played
nytg badges                      # every badge, earned or not, and your progress
nytg badges wordle --earned
```

Cookies are read from `--cookies`, then the `NYT_COOKIES` environment
variable, then the active profile.

### Archiving

```bash
nytg archive connections --from first --out puzzles/
```

saves each date as `puzzles/connections/YYYY-MM-DD.json`. For the few dates
with two crosswords (a special puzzle alongside the daily), each
is saved as `YYYY-MM-DD-ID.json`. Run it again to
resume: saved dates are skipped. A `manifest.json` records when each file was
fetched, NYT's update time and a hash; with `--overwrite`, puzzles NYT has
since changed keep their previous version in `revisions/`. Crosswords can be archived as crossword files
with `--as puz`, `--as ipuz` or `--as xml`; puzzles that can't be saved in that
format are listed as unsupported. Games: `wordle`, `connections`, `strands`,
`spelling-bee`, `letter-boxed`, `crossword-daily`, `crossword-mini` and
`crossword-midi`.

### Output formats

Every command takes `--format` (`-f`), like gcloud:

| Format | Output |
|---|---|
| `table` | Tables and grids (the default) |
| `json`, `yaml` | All the data |
| `csv` | One row per item, nested fields as dotted columns |
| `value(FIELD,...)` | Tab separated values for scripts, e.g. `value(categories[0].title)` |

```bash
nytg wordle --answers -f "value(solution)"
nytg stats -f json | jq '.[] | select(.game == "Wordle")'
```

### Profiles and settings

Settings are saved per profile in `~/.config/nytg/config.ini` (readable only
by you), similar to gcloud configurations:

```bash
nytg config set format json      # default output format for this profile
nytg config list
nytg --profile alice auth login  # a second NYT account
nytg config profiles activate alice
nytg config profiles list
```

`--profile` or `NYTG_PROFILE` picks a profile for one command. Run
`nytg --install-completion` for shell completion.

### Building your own command line

`nytgames.cli.extension` lets you build a command line with every `nytg`
command plus your own, sharing its root options (`--profile`, `--cookies`,
`--format`), output formats and error messages:

```python
import typer
from nytgames.cli.extension import FormatOption, create_app, emit, get_client, run

app = create_app(name="mytool", help="My NYT tools.", version="1.0.0")
db = typer.Typer(help="Query my archive.")
app.add_typer(db, name="db")


@db.command("midis")
def midis(fmt: FormatOption = None) -> None:
    """September's Midi crosswords."""
    puzzles = get_client().archive("crossword_midi", "2026-09-01", "2026-09-30")
    emit([{"date": p.print_date, "by": p.byline} for p in puzzles], fmt)


def main() -> None:   # point your [project.scripts] entry here
    run(app)
```

Each `create_app()` call returns an independent app. `emit(data, fmt,
table)` prints JSON-compatible data in the requested format, with an optional
function that renders the table format. `get_client()` returns a client with
the cookies `nytg` would use. The other modules in `nytgames.cli` are
internal.

## MCP server for AI agents

The optional `mcp` extra installs `nytg-mcp`, a local
[Model Context Protocol](https://modelcontextprotocol.io) server, so coding
agents and other MCP clients can use the NYT Games directly: ask Claude Code
for a Connections hint, your Saturday solve times, or to export yesterday's
crossword to `.puz`.

```bash
# Claude Code
claude mcp add nytimes-games -- uvx --from "nytimes-games[mcp]" nytg-mcp
```

For other clients (Claude Desktop, Cursor, VS Code and so on), add a stdio
server with the command `uvx` and the arguments
`--from nytimes-games[mcp] nytg-mcp`, or install the package and use the
command `nytg-mcp`.

| Tools | What they do |
|---|---|
| `wordle`, `connections`, `strands`, `spelling_bee`, `letter_boxed`, `crossword` | Puzzles for any date; crosswords include each entry's clue, position and crossings |
| `wordlebot_summary`, `puzzle_archive` | How everyone did on a Wordle; puzzle IDs for a date range |
| `bonus_week`, `bonus_puzzle` | The weekly Bonus Puzzles: Wordle in 1, Connections 3x3, Colorful Strands and bonus crosswords |
| `stats`, `today`, `crossword_history`, `wordle_history`, `spelling_bee_history`, `bonus_history`, `wordlebot`, `badges` | Your stats, progress, WordleBot analysis and badges (need cookies) |
| `export_crossword` | Save a crossword as `.puz`, `.ipuz` or `.xml`, optionally with your progress |

- Answers are hidden unless the agent passes `include_answers`, and the server
  tells agents to leave them hidden while you're still solving.
- Your own data uses the same cookies as `nytg`: `nytg auth login`, or set
  `NYT_COOKIES` in the server's environment. Cookie values are never returned
  or logged.
- Every tool is read-only except `export_crossword`, which only writes the file
  you ask for and won't overwrite one unless asked.

## REST API

The optional `api` extra serves everything as a REST API with
[FastAPI](https://fastapi.tiangolo.com/), including interactive docs at
`/docs`.

```bash
pip install "nytimes-games[api]"
uvicorn nytgames.api:app
```

To customize it, write your own `main.py`:

```python
from nytgames.api import create_app

app = create_app(title="My NYT Games API")   # any FastAPI settings
```

Or mount the routes in an existing FastAPI app:

```python
from fastapi import FastAPI
from nytgames.api import add_exception_handlers, router

app = FastAPI()
app.include_router(router, prefix="/nyt")
add_exception_handlers(app)   # NYT errors become 404s and 403s instead of 500s
```

By default each request is made with the cookies sent to the API:

```bash
curl -H "Cookie: NYT-S=..." http://localhost:8000/player/stats
```

To use your own cookies for every request instead, override the client:

```python
from nytgames import NYTGamesClient
from nytgames.api import get_client

app.dependency_overrides[get_client] = lambda: NYTGamesClient(cookies="NYT-S=...")
```

Anyone who can reach that API can then see your stats and progress, so keep it
private.

[`examples/api`](examples/api) has a complete `main.py` and `Dockerfile` for
running your own instance in a container.

### Endpoints

| Route | NYT endpoint |
|---|---|
| `GET /archive/{game}/{date_start}/{date_end}` | `svc/games/v1/archive/{game}/{date_start}/{date_end}` |
| `GET /badges` | `svc/games/badges/trophy-case/{game}` for each game |
| `GET /badges/{game}` | `svc/games/badges/trophy-case/{game}` |
| `GET /bonus/week/{date}` | `svc/games/bonus/week/v1/{date}.json` |
| `GET /bonus/wordle-in-one/{slug}` | `svc/wordle-in-one/v1/bonus/{slug}.json` |
| `GET /bonus/connections/{slug}` | `svc/connections/v2/bonus/{slug}.json` |
| `GET /bonus/strands/{slug}` | `svc/strands/v2/bonus/{slug}.json` |
| `GET /bonus/{wordle-in-one,connections,strands}/latest` | `svc/games/state/{wordle_in_one,connections_bonus,strands_bonus}/latests` |
| `GET /connections/latest` | `svc/games/state/connections/latests` |
| `GET /connections/{date}` | `svc/connections/v2/{date}.json` |
| `GET /crosswords/daily/today` | `svc/crosswords/v6/puzzle/daily.json` |
| `GET /crosswords/daily/{date}` | `svc/crosswords/v6/puzzle/daily/{date}.json` |
| `GET /crosswords/mini/today` | `svc/crosswords/v6/puzzle/mini.json` |
| `GET /crosswords/mini/{date}` | `svc/crosswords/v6/puzzle/mini/{date}.json` |
| `GET /crosswords/midi/today` | `svc/crosswords/v6/puzzle/midi.json` |
| `GET /crosswords/midi/{date}` | `svc/crosswords/v6/puzzle/midi/{date}.json` |
| `GET /crosswords/bonus/{date}` | `svc/crosswords/v6/puzzle/bonus/{date}.json` |
| `GET /crosswords/{publish_type}/{date}/download?format=puz` | A `.puz`, `.ipuz` or `.xml` file (`&progress=true` adds your progress) |
| `GET /crosswords/puzzles` | `svc/crosswords/v3/puzzles.json` |
| `GET /crosswords/id/{puzzle_id}` | `svc/crosswords/v6/puzzle/{puzzle_id}.json` |
| `GET /crosswords/oracle/{publish_type}` | `svc/crosswords/v2/oracle/{publish_type}.json` |
| `GET /crosswords/game/{game_id}?publish_type=daily` | `svc/games/state/crossword_{publish_type}/latests` |
| `GET /letter-boxed/{date}` | `svc/letter-boxed/v1/{date}.json` |
| `GET /player/stats` | `svc/games/state/wordleV2/latests?puzzle_ids=0` |
| `GET /spelling-bee` | Scraped from `puzzles/spelling-bee` |
| `GET /spelling-bee/latest` | `svc/games/state/spelling_bee/latests` |
| `GET /spelling-bee/{date}` | `svc/spelling-bee/v1/{date}.json` |
| `GET /spelling-bee/{date}/hints` | Computed from the puzzle above |
| `GET /strands/latest` | `svc/games/state/strands/latests` |
| `GET /strands/{date}` | `svc/strands/v2/{date}.json` |
| `GET /wordlebot` | `svc/int/run/cubby/public-api/v1/responses/wordlebot/reader` (today, needs cookies) |
| `GET /wordlebot/{date}/summary` | `static01.nyt.com/newsgraphics/2022/wordlebot/{solution}-{date}/summary.json` |
| `GET /wordle/latest` | `svc/games/state/wordleV2/latests` |
| `GET /wordle/{date}` | `svc/wordle/v2/{date}.json` |

NYT errors are returned with NYT's status code, for example 404 for a date
with no puzzle.

## How it works

NYT's games load their puzzles and your saved games from JSON endpoints on
www.nytimes.com, none of which need a login for puzzles:

- **Puzzles** come from one endpoint per game and date, such as
  `/svc/wordle/v2/2025-06-12.json`.
- **Your saved games and stats** come from the games' state endpoint,
  `/svc/games/state/{game}/latests`, with your `NYT-S` cookie.
- **Spelling Bee's** game page embeds the current puzzles in a script.
- **WordleBot's** summaries are static files on static01.nyt.com.

[docs/endpoints.md](docs/endpoints.md) has the details: endpoints, limits and quirks.

## Staying current with NYT

NYT changes these APIs without notice. Every morning a
[live check](https://github.com/lukwam/nytimes-games/actions/workflows/live.yml)
fetches a real puzzle from every game and endpoint, exports today's Mini
to every file format and runs the live tests. The **NYT live check** badge above shows the latest
result and date, and failures open an issue automatically.

## Contributing

NYT changes these APIs without notice, so bug reports with the failing date
and error are very welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) to set up a
development environment.

## License

MIT. This project is not affiliated with or endorsed by The New York Times.
NYT puzzles are copyrighted by The New York Times; please respect their terms
of service and don't republish puzzle content.

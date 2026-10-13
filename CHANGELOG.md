# Changelog

All notable changes to this project. The project follows
[Semantic Versioning](https://semver.org/); while it's below 1.0, minor
versions may include breaking changes.

## 0.11.5 (2026-10-13)

### Fixed

- Source distributions include the whole test tree (`tests/__init__.py`,
  `support.py`, `conftest.py` and the fixtures), the scripts the tests load,
  and the docs and contributor files, so an extracted sdist runs its own
  offline tests. CI and the publish workflow check that with
  `scripts/check_sdist.sh`, which builds a wheel from the extracted sdist
  and runs its tests away from the checkout. (#66)
- A `Retry-After` longer than 60 seconds is no longer cut short. The client
  waits as long as NYT asks, up to 5 minutes; for a longer wait it raises
  the error at once instead of retrying early, with
  `NYTGamesRateLimitError.retry_after` set. The exponential backoff is still
  capped at 60 seconds, and a `Retry-After` that isn't a finite number of
  seconds or a date is ignored. (#64)

- `nytg archive --overwrite` keeps the saved puzzle if writing its update
  fails. It used to move the file into `revisions/` first, so a failed write
  left it missing; now the old file is copied to `revisions/` and replaced
  only once the new one is completely written. `manifest.json` is written
  the same way, so an interrupted run leaves the previous complete manifest.
  A file that's on disk but missing from the manifest, as after an
  interrupted run, is added to the manifest as it is the next time. (#61)
- Saving `config.ini`, which holds your cookies, is atomic. It used to be
  truncated and rewritten in place, so a failed or interrupted save could
  lose your profiles. The new contents go to a private (0600) temporary file
  that replaces the config only once complete, and the config stays 0600
  even if it had been made readable by others. `active_profile` is written
  atomically too. (#68)
- Crossword exports with your saved progress skip saved entries that don't
  name a square of the grid. A negative index used to fill a square from the
  end (`-1` filled the last one), and a large negative or non-numeric one
  raised `IndexError` or `ValueError`. Revealed and penciled squares are
  checked the same way. (#67)

## 0.11.4 (2026-10-12)

### Fixed

- The temporary file used to replace a file with `overwrite` is private
  (0600) from the moment it's created. In 0.11.3 it started out readable
  under your umask and was made private just before the data was written,
  so a reader that opened it in that moment could still read the data. A
  new file's permissions now come from an empty file created and removed
  to find what your umask allows. (#56)

## 0.11.3 (2026-10-12)

### Fixed

- When a crossword export or `nytg ... --save` replaced a file with
  `overwrite`, the new content sat in a temporary file readable under your
  umask (often 0644) until it was moved into place, even when the file being
  replaced was private. The temporary file is now private (0600) while it
  holds the data; the final file's permissions are unchanged. (#56)

## 0.11.2 (2026-10-12)

### Fixed

- `NYTGamesParseError` messages no longer include dictionary keys taken from
  NYT's response, which could be private too. Field paths keep the models'
  own field names and list indexes, and show anything else as `*`, as in
  `average.*: float_type`. (#44)
- A crossword exported with `overwrite` (or saved with `nytg ... --save`) to
  a new file got 0644 permissions even under a stricter umask, such as 077.
  New files now get the permissions your umask allows with or without
  `overwrite`, and a replaced file keeps its own. (#46)

## 0.11.1 (2026-10-12)

### Fixed

- The `mcp` and `cli` extras install `tzdata` on every platform. Without a
  system time zone database (Windows, slim containers), `nytg-mcp` failed to
  start and `nytg` failed on Linux, with `ZoneInfoNotFoundError`. CI now
  installs each extra alone, on Linux and Windows, and checks New York time
  without a system database. (#47)
- The REST API passes only the `NYT-S` login cookie on to NYT. It used to
  forward every cookie sent to it, so mounted in an app with its own session
  cookie, it sent that cookie to NYT too. A cookie that can't be sent is now
  a 400 instead of a 500. If you relied on other cookies reaching NYT,
  override `get_client`. (#45)
- The MCP server's `export_crossword` never replaces a file unless
  `overwrite` is set. It checked for the file before fetching the puzzle, so
  a file created in the meantime was overwritten anyway; the file is now
  created exclusively, and symlinks are never followed. With `overwrite`,
  the new file is written next to the old one and moved into place, so a
  failed write keeps the old file. `nytg ... --save` replaces files the same
  way. (#46)
- `export_crossword` is marked destructive in its MCP annotations, since
  `overwrite` replaces files. (#46)
- A response from NYT that's valid JSON but the wrong shape raises
  `NYTGamesParseError`, as documented. It used to escape as Pydantic's
  `ValidationError` or a `TypeError`, so the REST API answered 500 instead
  of 502. If you caught those, catch `NYTGamesParseError` (a `ValueError`)
  instead. (#44)
- Errors never include NYT's response values, which can be your saved games.
  `NYTGamesParseError` names the model, fields and error types only; the
  models hide input values in validation errors; and the MCP server, CLI and
  live check report these errors without them. The live check reports other
  unexpected errors by type and location only, since its failures are
  published in GitHub issues. (#44)

## 0.11.0 (2026-10-12)

### Changed

- **Breaking:** both clients now use [httpx](https://www.python-httpx.org/),
  and `requests` and `urllib3` are no longer dependencies. The HTTP layer
  matches atlantic-games's:
  - `NYTGamesClient(session=...)` is now `NYTGamesClient(http_client=...)`
    and takes an `httpx.Client`. As before, your client is used as is and not
    closed, but the client's retries now apply to it too.
  - The `NYTGamesClient.session` and `AsyncNYTGamesClient.http_client`
    attributes are gone; keep a reference to the client you pass in if you
    need it.
  - `NYTGamesHTTPError` no longer subclasses `requests.HTTPError`. It has
    `.status_code`, and `.response` is an `httpx.Response`. Catch
    `NYTGamesHTTPError` instead of `requests.HTTPError`, and
    `httpx.HTTPError` instead of `requests.RequestException` for connection
    errors.
  - Error messages read `HTTP 404 for <url>`.
- `NYTGamesClient` has `close()` and works as a context manager, like
  `AsyncNYTGamesClient`.
- The `async` extra is no longer needed, since httpx is a core dependency.
  It's kept, empty, so existing installs still work.

### Fixed

- The REST API closes its NYT client after each request instead of leaving
  the connection pool to garbage collection.
- The nightly live check expected 32 dailies in December 2022, but NYT no
  longer serves 2022-12-31's Supermega. It now checks that two months of
  dailies, more than one request's worth, come back with none dropped.

## 0.10.0 (2026-10-12)

### Added

- `pytest -m live` runs live tests against NYT (deselected by default), and
  the nightly live check runs them too.
- `docs/endpoints.md` documents NYT's endpoints, limits and quirks.
- The README's "Read-only" and "How it works" sections. The tests now check
  that the clients only send GET requests.

### Changed

- Linted with ruff, in CI and as a pre-commit hook.

### Fixed

- The REST API's `/docs` page lists the Badges and Bonus Puzzles routes under
  described tags.
- `nytg --format yaml` without PyYAML says how to install it instead of
  showing an import error.
- `nytg` hides your cookie values in "Couldn't read NYT's response" errors,
  as it does in its other errors.

## 0.9.7 (2026-10-12)

### Fixed

- `wordlebot_summary()` failed to validate summaries from 2021 to early
  2022, where NYT sends null percentiles for a mode (`hard-ps`,
  `normal-ps`) that had none yet. Percentiles for a mode can now be null.
  Found by gamesapp.

## 0.9.6 (2026-10-11)

### Added

- `AsyncNYTGamesClient`, an asyncio client with every method of
  `NYTGamesClient`, awaited (`async with AsyncNYTGamesClient() as client:`).
  It needs the new `async` extra (`pip install "nytimes-games[async]"`),
  which adds httpx; the base install and the sync client, still on
  requests, don't change. Errors, retries with backoff and cookie handling
  match the sync client. Closes #19.

### Changed

- Each endpoint is written once, as an operation both clients run (see
  `nytgames.transport`), so the two clients can't drift apart. Operations
  that use others, such as `badges()` or `wordlebot_summary()`, now call them
  directly, so overriding or patching a method on a client instance no
  longer changes those calls; patch `_get` to fake NYT's responses instead.

## 0.9.5 (2026-10-08)

### Fixed

- `player_stats()` raised a bare `KeyError: 'player'` for NYT accounts that
  have never played a game while signed in, since they have no NYT Games
  profile. It now raises `NYTGamesNoProfileError` (still a `KeyError`, so
  existing handlers keep working). `nytg stats`, the MCP tools and the API
  (404) explain it. Found by gamesapp.
- `spelling_bee_latest()` no longer requires `player`, like the other saved
  game methods.
- `bonus_week()` raises `NYTGamesParseError` instead of `KeyError` for an
  unexpected response.

## 0.9.4 (2026-10-08)

### Added

- The weekly Bonus Puzzles (new on Wednesdays since 2026-08-26):
  `bonus_week(date)` lists the week's drop that includes a date, with each
  puzzle's title, byline, ID and slug, and `bonus_weeks(date_start,
  date_end)` lists a range. `bonus_puzzle(listing)` fetches any of them:
  `wordle_in_one(slug)` (new `WordleInOnePuzzle`: five rounds, each a
  starting guess and a solution), `connections_bonus(slug)` (Connections
  3x3), `strands_bonus(slug)` (Colorful Strands, with `themeColors` and
  `themeEmojis`) and `crossword_by_id()` for the Mystery Mini, Easy Mode and
  Special crosswords. Puzzles load without cookies. Requested by
  nyt-puzzles.
- Your bonus games: `wordle_in_one_latest(puzzle_ids)`,
  `connections_latest(puzzle_ids, bonus=True)`,
  `strands_latest(puzzle_ids, bonus=True)`, and
  `crossword_game(puzzle_ids, "bonus")`, by the `id` in a week's listing.
- `nytg bonus week|wordle-in-one|connections|strands|crossword` and
  `nytg history bonus`; `bonus_week`, `bonus_puzzle` and `bonus_history`
  MCP tools; and `/bonus/...` API routes.

### Fixed

- `ConnectionsPuzzle.board()` and `nytg connections` assumed a 4x4 board;
  they now fit the puzzle (3x3 for Connections 3x3).

## 0.9.3 (2026-10-06)

### Added

- Badges. `badges(games)` and `trophy_case(game)` return every Wordle,
  Connections, Strands and Spelling Bee badge, earned or not, with your
  progress, from the games app's trophy case
  (`/svc/games/badges/trophy-case/{game}`, needs cookies). `unearned`
  means not fully earned, so it includes tiered badges with levels still to
  reach; `TrophyCaseGame.badges` lists each badge once.
- `badges_trophy_shelf` on `wordle_latest()`, `connections_latest()`,
  `strands_latest()`, `spelling_bee_latest()` and `crossword_game()`: the
  three badges NYT features for the game, which were dropped before.
  Requested by nyt-puzzles.
- `Badge`, a lenient model (fields vary by badge type), with `is_earned`,
  `level`, `next_level`, `earned_dates` and `name`.
- `nytgames.badges`: names, descriptions and SVG artwork URLs for all 35
  badges, at any level, from a copy of the games app's table (NYT doesn't
  serve it from an API). `Badge.info` returns a badge's entry, or None for
  new badges not in the copy yet; the daily live check flags those.
- `nytg badges [game] [--earned]`, the `badges` MCP tool, and `GET /badges`
  and `GET /badges/{game}` in the API.

## 0.9.2 (2026-10-05)

### Added

- `connections_latest(puzzle_ids)` and `strands_latest(puzzle_ids)`: your
  saved Connections and Strands games, shaped like `wordle_latest()` (up to
  30 puzzle IDs per call; `states` only includes games you've played). Game
  data is lenient, since older games vary: every field is optional and extra
  fields are kept. `isPlayingArchive` tells games played from the archive
  apart. Requested by nyt-puzzles.
- `nytg history connections` (won or lost, mistakes, groups found) and
  `nytg history strands` (solved, other words found).
- `GET /connections/latest` and `GET /strands/latest` in the API.

## 0.9.1 (2026-10-04)

### Fixed

- `nytg archive crossword-*` saved only one puzzle on dates with two (such as
  2022-12-31, where it kept the Supermega and skipped the daily). Crosswords
  are now listed from the games archive and fetched by ID; dates with two
  puzzles save each as `YYYY-MM-DD-ID`, and single-puzzle dates keep their
  `YYYY-MM-DD` names, so existing archives resume as before. Future dates
  are still fetched by date.

## 0.9.0 (2026-10-04)

### Added

- `nytg-mcp`, a local MCP server for AI agents, behind the `mcp` extra
  (`pip install "nytimes-games[mcp]"`): 15 tools for puzzles (with crossword
  entries and crossings), WordleBot, the puzzle archive, your stats, today's
  games and histories, and crossword export. Answers are hidden unless
  `include_answers` is set; cookies come from `NYT_COOKIES` or your nytg
  profile and are never returned or logged; every tool is read-only except
  `export_crossword`.
- `nytgames.views`: the plain data behind nytg's commands (puzzle views with
  answers hidden, today, histories, WordleBot comparisons), shared by nytg and
  the MCP server.

## 0.8.4 (2026-10-04)

### Fixed

- Saved game states from older games failed validation, failing whole
  batches in `spelling_bee_latest()` and `wordle_latest()`: Spelling Bee
  games without a `rank`, and Wordle games in a rounds-based format
  (`rounds`, `currentRoundIndex`, `puzzleComplete`, no guesses). These fields
  are now optional, the rounds-based fields are typed, and
  `WordleGameData.rounds_format` tells the formats apart. `print_date` (often
  empty on older games) and `timestamp` are optional too. Found by
  nyt-puzzles.
- `nytg today` and `nytg history` show these games as "played".

## 0.8.3 (2026-10-04)

### Security

- `nytg` could print cookie values in a traceback when `NYT_COOKIES` or
  `--cookies` held a Cookie-Editor JSON export: it was parsed as a Cookie
  header string, producing an invalid header whose error message contained
  every cookie. Reported by nyt-puzzles. If you hit this, rotate your NYT
  cookies (log out and back in).

### Fixed

- `parse_cookies()` (and so `NYTGamesClient`, `NYT_COOKIES` and
  `--cookies`) accepts a JSON export or JSON object as a string.
- Cookies are checked before any request; invalid ones raise `ValueError`
  naming the cookie but never showing its value.
- `nytg` never prints raw tracebacks: unexpected errors print a one-line
  message with any cookie values redacted.

## 0.8.2 (2026-10-04)

### Added

- WordleBot: `wordlebot()` returns your analysis of today's Wordle (luck and
  skill, overall and by round; needs cookies, today only, after you've opened
  WordleBot), and `wordlebot_summary(date)` returns how everyone did on any
  day since 2021-06-19, including the bot's solve paths.
- `nytg wordlebot [DATE]` compares your luck and skill with everyone's and
  shows where your skill falls among players; `--answers` shows the bot's
  paths. API routes `/wordlebot` and `/wordlebot/{date}/summary`.
- Cookies are only sent to NYT's main site, never to its static file server.

## 0.8.1 (2026-10-04)

### Fixed

- `archive()` could silently drop the first day of a 31-day window when a
  date in it had two puzzles, because NYT returns at most 31 puzzles per
  request (e.g. 2022-12-01, next to 2022-12-31's daily and Supermega).
  Windows that hit the limit are now split and fetched again. Both puzzles on
  a two-puzzle date are returned, sorted by date and ID. Found by nyt-puzzles.

### Added

- `crossword_by_id(puzzle_id)` for any crossword by ID, such as the second
  puzzle on a date that has two. API route `/crosswords/id/{puzzle_id}` and
  `nytg crossword --id`.

## 0.8.0 (2026-10-04)

### Added

- A live check of every game against NYT runs every morning, with a README
  badge showing the latest result. Failures open an issue automatically.
- A coverage badge.
- Puzzle structure helpers: `CrosswordPuzzle.entries()` (each entry's clue,
  full answer, squares, coordinates, crossings and referenced clues) and
  `.squares()`, `StrandsPuzzle.words()` (words with their paths) and
  `ConnectionsPuzzle.board()`. Special puzzles are kept as they are.

- `formats.fidelity(puzzle, fmt, game=None)`: what an export approximates or
  leaves out, such as shading shown as circles in .puz or italics in clues.
  `nytg crossword --save` prints these notes.
- `nytg archive` keeps a `manifest.json` per game with each file's retrieval
  time, NYT's update time, the nytimes-games version and a SHA-256 hash.
  With `--overwrite`, puzzles NYT has changed keep their previous version
  in `revisions/` and are reported as changed.
- Examples: a Letter Boxed solver, clue reuse across crosswords, and solve
  times by weekday and constructor.
- A README capability matrix: what each method returns and which fields are
  spoilers.
- Retries with exponential backoff for failed connections, timeouts, rate
  limits and NYT server errors, honoring `Retry-After`
  (`NYTGamesClient(retries=3, backoff=0.5)`). Sessions you pass in are used
  as is.
- `NYTGamesRateLimitError` (429 after retries) with `retry_after`, and a
  matching nytg message.
- `NYTGamesClient(base_url=...)`, for proxies and testing.
- `urllib3` is declared as a dependency (it comes with requests).

### Fixed

- `crossword_puzzles()` returned a validation error when NYT sends null
  results (for empty ranges and ranges that are too long); it now returns an
  empty list. Its docs recommend ranges of 90 days or less.

## 0.7.0 (2026-10-04)

### Added

- `nytgames.formats`: export crosswords to Across Lite `.puz`, `.ipuz` and
  Crossword Compiler rectangular-puzzle `.xml`, with the user's saved
  progress (fill, revealed and penciled squares, and the .puz timer).
  Rebus squares, circles and shading are kept where the format allows.
  `export()`, `to_puz()`, `to_ipuz()`, `to_xml()` and `export_problems()`.
- `NYTGamesExportError` for puzzles whose gimmicks a format can't represent,
  with the reasons.
- `nytg crossword ... --save FILE [--progress]` and
  `nytg archive crossword-* --as puz|ipuz|xml`.
- API route `/crosswords/{publish_type}/{date}/download?format=puz`.

## 0.6.1 (2026-10-04)

### Fixed

- Crosswords with special square labels no longer fail validation.
  `CrosswordPuzzleCell.label` is still an int for numbered squares, and a
  string for text labels such as `CW` or arrows (2000-02-13, 2007-07-01,
  2017-07-02). `CrosswordPuzzleClue.label` is optional, for special clues
  like 2016-03-24's "Around" clue.
- `nytg crossword --answers` no longer repeats letters in clues that turn a
  corner.

## 0.6.0 (2026-10-04)

### Added

- `nytgames.cli.extension`: a public API for building command lines on top
  of nytg. `create_app(name=, help=, version=)` returns an independent Typer
  app with every nytg command and root option, and `run(app)` runs it with
  nytg's error messages and exit codes. `emit()`, `FormatOption`,
  `get_client()`, `resolve_cookies()`, `active_profile()`, `get_setting()`,
  `parse_date()`, `key_value_table()` and the Rich consoles help extension
  commands behave like nytg's. `create_app` and `run` are also importable
  from `nytgames.cli`.

### Changed

- Error messages name the running command, for example `mytool auth login`.

## 0.5.0 (2026-10-04)

### Added

- `nytg`, a command line tool, behind the `cli` extra
  (`pip install "nytimes-games[cli]"`): puzzles for every game with answers
  hidden unless `--answers`, Spelling Bee hints, crossword grids and clues,
  `stats`, `today`, `history` (crossword, Wordle, Spelling Bee), resumable
  `archive`, gcloud-style `--format` (table, json, yaml, csv, value()),
  `auth login`, and settings and profiles in `~/.config/nytg/config.ini`.
- `archive(game, date_start, date_end)`: the puzzles published in a date
  range, with their IDs, for Wordle, Connections, Strands and the Daily, Mini
  and Midi crosswords, from NYT's games archive. Ranges longer than 31 days
  are split automatically. Also served by the API at
  `/archive/{game}/{date_start}/{date_end}`.
- `crossword_game()`, `wordle_latest()` and `spelling_bee_latest()` accept a
  list of puzzle IDs.

- Python 3.14 support. Python 3.15 is tested while it's in pre-release.

### Fixed

- `crossword_puzzles("midi")` raises `ValueError` instead of returning Daily
  puzzles, which is what NYT's list returns for Midi; use `archive()` for
  Midi puzzles. The API returns 400.

## 0.4.0 (2026-10-04)

### Added

- `nytgames.api`: the REST API is now part of the package, behind the `api`
  extra (`pip install "nytimes-games[api]"`). Run it with
  `uvicorn nytgames.api:app`, customize it with `create_app()`, or mount
  `router` in your own FastAPI app with `add_exception_handlers()`. Override
  the `get_client` dependency to use your own cookies.
- `examples/api`: an example `main.py` and `Dockerfile` for running your own
  instance.
- `NYTGamesParseError` responses from the API return 502 instead of 500.

### Changed

- The package source moved to `src/nytgames` (src layout). Imports are
  unchanged.
- The API no longer pretty-prints JSON responses and no longer configures
  logging.

### Removed

- The standalone `api/` service and its deployment files.

## 0.3.2 (2026-10-04)

### Fixed

- Connections picture puzzles, whose cards have `image_url` and
  `image_alt_text` instead of `content`. Added `card.text` and
  `ConnectionsPuzzle.illustrator`.

## 0.3.1 (2026-10-04)

- First release on PyPI, as `nytimes-games`. Ships `py.typed`.

## 0.3.0 (2026-10-04)

### Added

- `spelling_bee_puzzle(date)`: any Spelling Bee from 2018-05-06.

## 0.2.1 (2026-10-04)

- Corrected the documented Letter Boxed date range.

## 0.2.0 (2026-10-04)

### Added

- `letter_boxed(date)`.
- `player_stats()`: your stats for every game.
- Typed errors: `NYTGamesHTTPError`, `NYTGamesAuthenticationError`,
  `NYTGamesNotFoundError`, `NYTGamesParseError`.
- A `nytimes-games` User-Agent.

## 0.1.0 (2026-10-04)

- First release as an installable library, with endpoints updated for NYT's
  current APIs.

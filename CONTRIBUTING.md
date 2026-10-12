# Contributing

Thanks for helping. NYT changes its games APIs without notice, so reports of
something that stopped working are as valuable as code.

## Reporting a bug

Open an issue with:

- the method or `nytg` command you ran (for example `connections("2026-05-06")`)
- the full error message
- your `nytimes-games` version (`python -c "import nytgames; print(nytgames.__version__)"`)

Never include your `NYT-S` cookie or other cookies in an issue.

## Development setup

```bash
git clone https://github.com/lukwam/nytimes-games.git
cd nytimes-games
python -m venv .venv
source .venv/bin/activate
pip install -e ".[api,cli,mcp,test]"
pytest
```

The tests mock NYT, so they run offline and don't need cookies.
Each client test runs against both `NYTGamesClient` and
`AsyncNYTGamesClient`.

Lint with ruff, which CI also runs, or install the pre-commit hooks to run it
on every commit:

```bash
ruff check
pre-commit install
```

Run the API locally with auto-reload:

```bash
uvicorn nytgames.api:app --reload
```

## Project layout

```
src/nytgames/
    client.py        NYTGamesClient and AsyncNYTGamesClient: one operation per NYT endpoint
    transport.py     Requests, retries and error mapping for both clients
    models.py        Pydantic models for NYT's responses
    exceptions.py    Error types
    spelling_bee.py  Spelling Bee hints
    badges.py        Badge names, descriptions and artwork, from badges.json
    formats.py       Crossword export: .puz, .ipuz and Crossword Compiler .xml
    structure.py     Crossword entries and squares, Strands word paths
    api.py           Optional FastAPI app and router (the "api" extra)
    views.py         Plain data views shared by nytg and the MCP server
    mcp_server.py    Optional MCP server for AI agents (the "mcp" extra)
    cli/             Optional nytg command line (the "cli" extra)
        app.py       Root command, global options and error messages
        puzzles.py   Puzzle commands
        bonus.py     Bonus Puzzles commands
        player.py    stats, today and history
        archive.py   archive
        settings.py  auth and config commands
        output.py    --format handling, shared by every command
        extension.py Public API for tools built on nytg; keep it backwards compatible
tests/
    fixtures/        Real NYT responses; saved games and stats are made up, in the tests
examples/            Small scripts built on the package, and an example API with a Dockerfile
docs/                endpoints.md: the endpoints, limits and quirks behind each game; and the
                     README screenshot, regenerated with docs/make_screenshot.py
```

## How the client works

Each client method is a generator in `_Operations` that yields
`transport.Request`s and receives the decoded responses. `run_sync` drives
it with an `httpx.Client` and `run_async` with an `httpx.AsyncClient`, so
a new endpoint only has to be written once. Errors from a request are thrown
into the generator, so an operation can catch a 404 and stop.

Cookies are only sent to `www.nytimes.com` (or the client's `base_url`),
never to other hosts such as `static01.nyt.com`. Every request is a GET;
the tests fail if a client sends anything else.

## Fixtures

Fixtures are real responses, saved as NYT sent them; pre-commit leaves them
alone. Before adding one:

- remove cookies, login tokens, user IDs and anything else personal; keep
  saved games and stats made up, in the tests (see `tests/support.py`)
- keep it small: trim a page to the part that matters, as
  `spelling_bee/page.html` is

## Checking against NYT

The tests mock NYT. To check the real APIs, run the live tests (about one
request each) or the full live check that runs every morning in GitHub
Actions:

```bash
pytest -m live
python scripts/live_check.py
```

Set `NYT_COOKIES` to also check the endpoints that need cookies.

## Adding or fixing an endpoint

1. Add an operation to `_Operations` in `client.py`, and a model in `models.py`.
   An operation is a generator: `data = yield Request(path, params)` makes a
   request, and `yield from _Operations.other(self, ...)` calls another
   operation. Both clients get the method from it, so write each endpoint
   once. Models allow extra fields, so only type the fields you use or
   document.
2. Add a route to `api.py` that calls the client method, and a command to
   `cli/` if it's useful on the command line. Commands build JSON-compatible
   data and pass it to `output.emit()` with a table renderer, so every output
   format works. Hide answers unless `--answers` is given.
3. Add tests that mock the NYT response with `respx`, using a fixture, and
   check the method against NYT before opening a pull request.
4. Update the tables in `README.md`, note anything new about the endpoint in
   `docs/endpoints.md`, and add a line to `CHANGELOG.md`.

## Pull requests

Tests run on Python 3.10 to 3.14 for every pull request, plus the next
Python release while it's in pre-release. Keep changes focused,
and explain in the description what you checked against NYT.

## Releases

Maintainers release by bumping `__version__` in `src/nytgames/__init__.py`,
updating `CHANGELOG.md`, and pushing a `vX.Y.Z` tag. The publish workflow
checks the tag matches the version, runs the tests and publishes to TestPyPI,
then PyPI. To try a release first, run the "Publish to PyPI" workflow by hand
(Actions → Run workflow) on your branch: it publishes to
[TestPyPI](https://test.pypi.org/project/nytimes-games/) only, and the tag
skips that version there later.

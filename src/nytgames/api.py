"""FastAPI app and router for the NYT Games API.

Requires the `api` extra::

    pip install "nytimes-games[api]"

Run the ready-made app with ``uvicorn nytgames.api:app``, build your own with
``create_app()``, or mount ``router`` in an existing FastAPI app (then call
``add_exception_handlers()`` on that app too).

By default each request is made with the cookies sent to the API. To use other
cookies, such as your own from a secret, override the ``get_client``
dependency::

    app = create_app()
    app.dependency_overrides[get_client] = lambda: NYTGamesClient(cookies=...)
"""
import enum
from typing import Any
from typing import Optional

try:
    from fastapi import APIRouter
    from fastapi import Depends
    from fastapi import FastAPI
    from fastapi import HTTPException
    from fastapi import Path
    from fastapi import Query
    from fastapi import Request
    from fastapi.responses import JSONResponse
    from fastapi.responses import Response
except ImportError as err:  # pragma: no cover
    raise ImportError(
        'nytgames.api requires FastAPI. Install it with: pip install "nytimes-games[api]"'
    ) from err

import requests

from nytgames import NYTGamesClient
from nytgames import NYTGamesNoProfileError
from nytgames import NYTGamesParseError
from nytgames import __version__
from nytgames import formats
from nytgames import spelling_bee_hints
from nytgames.models import ArchiveGame
from nytgames.models import ArchivePuzzle
from nytgames.models import BadgeGame
from nytgames.models import BonusWeek
from nytgames.models import ConnectionsLatest
from nytgames.models import ConnectionsPuzzle
from nytgames.models import CrosswordGame
from nytgames.models import CrosswordOracle
from nytgames.models import CrosswordPublishType
from nytgames.models import CrosswordPuzzle
from nytgames.models import CrosswordPuzzlesList
from nytgames.models import LetterBoxedPuzzle
from nytgames.models import Player
from nytgames.models import SpellingBeeGameData
from nytgames.models import SpellingBeeGameDay
from nytgames.models import SpellingBeeLatest
from nytgames.models import StrandsLatest
from nytgames.models import StrandsPuzzle
from nytgames.models import TrophyCase
from nytgames.models import WordleBotAnalysis
from nytgames.models import WordleBotSummary
from nytgames.models import WordleInOneLatest
from nytgames.models import WordleInOnePuzzle
from nytgames.models import WordlePuzzle
from nytgames.models import WordlePuzzlesList

__all__ = ["add_exception_handlers", "app", "create_app", "get_client", "router"]

OPENAPI_TAGS = [
    {"name": "Archive", "description": "Puzzle IDs and dates for a date range"},
    {"name": "Badges", "description": "Badges and your progress toward them"},
    {"name": "Bonus Puzzles", "description": "The weekly Bonus Puzzles drop and your bonus games"},
    {"name": "Connections", "description": "Connections Puzzles operations"},
    {"name": "Crosswords", "description": "Crossword Puzzles operations"},
    {"name": "Crosswords - Bonus", "description": "Crossword Bonus Puzzles operations"},
    {"name": "Crosswords - Daily", "description": "Crossword Daily Puzzles operations"},
    {"name": "Crosswords - Midi", "description": "Crossword Midi Puzzles operations"},
    {"name": "Crosswords - Mini", "description": "Crossword Mini Puzzles operations"},
    {"name": "Letter Boxed", "description": "Letter Boxed Puzzles operations"},
    {"name": "Player", "description": "Player stats operations"},
    {"name": "Spelling Bee", "description": "Spelling Bee Puzzles operations"},
    {"name": "Strands", "description": "Strands Puzzles operations"},
    {"name": "Wordle", "description": "Wordle Puzzles operations"},
    {"name": "WordleBot", "description": "WordleBot analysis and daily summaries"},
]

router = APIRouter()


def get_client(request: Request) -> NYTGamesClient:
    """Return an NYT Games client using the cookies sent with the request."""
    return NYTGamesClient(cookies=request.cookies)


async def nyt_http_error_handler(request: Request, exc: requests.HTTPError) -> JSONResponse:
    """Return NYT HTTP errors with NYT's status code."""
    status_code = exc.response.status_code if exc.response is not None else 502
    return JSONResponse(
        status_code=status_code,
        content={"detail": f"NYT API returned {status_code}"},
    )


async def nyt_parse_error_handler(request: Request, exc: NYTGamesParseError) -> JSONResponse:
    """Return 502 when an NYT page did not contain the expected game data."""
    return JSONResponse(status_code=502, content={"detail": str(exc)})


async def nyt_no_profile_handler(request: Request, exc: NYTGamesNoProfileError) -> JSONResponse:
    """Return 404 when the NYT account has no NYT Games profile yet."""
    return JSONResponse(status_code=404, content={"detail": str(exc)})


def add_exception_handlers(app: FastAPI) -> None:
    """Return NYT errors from the client as HTTP responses instead of 500s."""
    app.add_exception_handler(requests.HTTPError, nyt_http_error_handler)
    app.add_exception_handler(NYTGamesNoProfileError, nyt_no_profile_handler)
    app.add_exception_handler(NYTGamesParseError, nyt_parse_error_handler)


def create_app(**kwargs: Any) -> FastAPI:
    """Return a FastAPI app serving the NYT Games API.

    Keyword arguments are passed to FastAPI and override the defaults, for
    example ``create_app(title="My NYT API", docs_url=None)``.
    """
    settings = {
        "title": "NYT Games API",
        "description": (
            "Unofficial API for the New York Times Games, built with "
            "[nytimes-games](https://github.com/lukwam/nytimes-games)."
        ),
        "version": __version__,
        "openapi_tags": OPENAPI_TAGS,
        "license_info": {"name": "MIT", "identifier": "MIT"},
    }
    settings.update(kwargs)
    app = FastAPI(**settings)
    app.include_router(router)
    add_exception_handlers(app)
    return app


# Archive
@router.get(
    "/archive/{game}/{date_start}/{date_end}",
    response_model=list[ArchivePuzzle],
    summary="List the puzzles published between two dates",
    tags=["Archive"],
)
def get_archive(
    game: ArchiveGame,
    client: NYTGamesClient = Depends(get_client),
    date_start: str = Path(..., examples=["2026-10-01"]),
    date_end: str = Path(..., examples=["2026-10-31"]),
) -> list[ArchivePuzzle]:
    """
    **List puzzles**

    Returns the ID and print date of each puzzle between two dates for
    connections, strands, wordle, crossword_daily, crossword_mini or
    crossword_midi. Ranges longer than 31 days are fetched 31 days at a time.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/games/v1/archive/{game}/{date_start}/{date_end}
    ```
    """
    return client.archive(game, date_start, date_end)


# Badges
@router.get(
    "/badges",
    response_model=TrophyCase,
    summary="List every badge for every game",
    tags=["Badges"],
)
def get_badges(client: NYTGamesClient = Depends(get_client)) -> TrophyCase:
    """
    **List badges**

    Returns every badge for Wordle, Connections, Strands and Spelling Bee,
    earned or not, with the user's progress. Requires the `NYT-S` cookie.
    Makes one request per game.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/games/badges/trophy-case/{game}
    ```
    """
    return client.badges()


@router.get(
    "/badges/{game}",
    response_model=TrophyCase,
    summary="List every badge for a game",
    tags=["Badges"],
)
def get_trophy_case(game: BadgeGame, client: NYTGamesClient = Depends(get_client)) -> TrophyCase:
    """
    **List a game's badges**

    Returns every badge for wordleV2, connections, strands or spelling_bee,
    earned or not, with the user's progress. Requires the `NYT-S` cookie.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/games/badges/trophy-case/{game}
    ```
    """
    return client.trophy_case(game)


# Bonus Puzzles
@router.get(
    "/bonus/week/{date}",
    response_model=BonusWeek,
    summary="List a week's Bonus Puzzles",
    tags=["Bonus Puzzles"])
def get_bonus_week(
    client: NYTGamesClient = Depends(get_client),
    date: str = Path(..., examples=["2026-10-07"]),
) -> BonusWeek:
    """
    **List a week's Bonus Puzzles**

    Returns the weekly Bonus Puzzles drop that includes a date: Wordle in 1,
    Connections 3x3, Colorful Strands and bonus crosswords, with each
    puzzle's ID and slug. Drops come out on Wednesdays from 2026-08-26.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/games/bonus/week/v1/{date}.json
    ```
    """
    return client.bonus_week(date)


@router.get(
    "/bonus/wordle-in-one/latest",
    response_model=WordleInOneLatest,
    summary="List your saved Wordle in 1 games",
    tags=["Bonus Puzzles"])
def list_latest_wordle_in_one(
    client: NYTGamesClient = Depends(get_client),
    puzzle_ids: str = Query(None, examples=["8,7,6"]),
) -> WordleInOneLatest:
    """
    **List your saved Wordle in 1 games**

    Returns the user's saved Wordle in 1 games for the puzzle IDs (the `id` in
    a bonus week's listing). Requires the `NYT-S` cookie.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/games/state/wordle_in_one/latests
    ```
    """
    return client.wordle_in_one_latest(puzzle_ids)


@router.get(
    "/bonus/connections/latest",
    response_model=ConnectionsLatest,
    summary="List your saved Connections bonus games",
    tags=["Bonus Puzzles"])
def list_latest_connections_bonus(
    client: NYTGamesClient = Depends(get_client),
    puzzle_ids: str = Query(None, examples=["8,7,6"]),
) -> ConnectionsLatest:
    """
    **List your saved Connections bonus games**

    Returns the user's saved Connections bonus games for the puzzle IDs (the `id` in
    a bonus week's listing). Requires the `NYT-S` cookie.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/games/state/connections_bonus/latests
    ```
    """
    return client.connections_latest(puzzle_ids, bonus=True)


@router.get(
    "/bonus/strands/latest",
    response_model=StrandsLatest,
    summary="List your saved Strands bonus games",
    tags=["Bonus Puzzles"])
def list_latest_strands_bonus(
    client: NYTGamesClient = Depends(get_client),
    puzzle_ids: str = Query(None, examples=["8,7,6"]),
) -> StrandsLatest:
    """
    **List your saved Strands bonus games**

    Returns the user's saved Strands bonus games for the puzzle IDs (the `id` in
    a bonus week's listing). Requires the `NYT-S` cookie.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/games/state/strands_bonus/latests
    ```
    """
    return client.strands_latest(puzzle_ids, bonus=True)


@router.get(
    "/bonus/wordle-in-one/{slug}",
    response_model=WordleInOnePuzzle,
    summary="Get a Wordle in 1 puzzle",
    tags=["Bonus Puzzles"])
def get_wordle_in_one(
    client: NYTGamesClient = Depends(get_client),
    slug: str = Path(..., examples=["2026-10-07-1270"]),
) -> WordleInOnePuzzle:
    """
    **Get a Wordle in 1 puzzle**

    Returns a Wordle in 1 bonus puzzle by its slug, from a bonus week's listing.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/wordle-in-one/v1/bonus/{slug}.json
    ```
    """
    return client.wordle_in_one(slug)


@router.get(
    "/bonus/connections/{slug}",
    response_model=ConnectionsPuzzle,
    summary="Get a Connections bonus puzzle",
    tags=["Bonus Puzzles"])
def get_connections_bonus(
    client: NYTGamesClient = Depends(get_client),
    slug: str = Path(..., examples=["2026-10-07-1270"]),
) -> ConnectionsPuzzle:
    """
    **Get a Connections bonus puzzle**

    Returns a Connections bonus bonus puzzle by its slug, from a bonus week's listing.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/connections/v2/bonus/{slug}.json
    ```
    """
    return client.connections_bonus(slug)


@router.get(
    "/bonus/strands/{slug}",
    response_model=StrandsPuzzle,
    summary="Get a Strands bonus puzzle",
    tags=["Bonus Puzzles"])
def get_strands_bonus(
    client: NYTGamesClient = Depends(get_client),
    slug: str = Path(..., examples=["2026-10-07-1270"]),
) -> StrandsPuzzle:
    """
    **Get a Strands bonus puzzle**

    Returns a Strands bonus bonus puzzle by its slug, from a bonus week's listing.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/strands/v2/bonus/{slug}.json
    ```
    """
    return client.strands_bonus(slug)


# Connections
@router.get(
    "/connections/latest",
    response_model=ConnectionsLatest,
    summary="List latest Connections puzzles",
    tags=["Connections"])
def list_latest_connections_puzzles(
    client: NYTGamesClient = Depends(get_client),
    puzzle_ids: str = Query(None, examples=["1,2,3,4,5,6,7"]),
) -> ConnectionsLatest:
    """
    **List latest Connections puzzles**

    Returns the user's saved Connections games for the puzzle IDs in the url
    parameters. Requires the `NYT-S` cookie.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/games/state/connections/latests
    ```
    """
    return client.connections_latest(puzzle_ids)


@router.get(
    "/connections/{date}",
    response_model=ConnectionsPuzzle,
    summary="Get the Connections puzzle for a specific date",
    tags=["Connections"],
)
def get_connections_puzzle(
    client: NYTGamesClient = Depends(get_client),
    date: str = Path(..., examples=["2023-06-12"]),
) -> ConnectionsPuzzle:
    """
    **Get a Connections puzzle**

    Returns the Connections puzzle for the date provided in the path parameter.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/connections/v2/{date}.json
    ```
    """
    return client.connections(date)


# Crosswords
@router.get(
    "/crosswords/game/{game_id}",
    response_model=CrosswordGame,
    summary="Get a Crossword Game",
    tags=["Crosswords"],
)
def get_crossword_game(
    client: NYTGamesClient = Depends(get_client),
    game_id: str = Path(..., examples=["24287"]),
    publish_type: CrosswordPublishType = Query(
        CrosswordPublishType.daily,
        examples=["daily"],
    ),
) -> CrosswordGame:
    """
    **Get a Crossword Game**

    Returns the user's saved game state for the puzzle ID provided in the path
    parameter. `states` is empty if the user has not played the puzzle.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/games/state/crossword_{publish_type}/latests?puzzle_ids={game_id}
    ```
    """
    return client.crossword_game(game_id, publish_type)


@router.get(
    "/crosswords/id/{puzzle_id}",
    response_model=CrosswordPuzzle,
    summary="Get a crossword by its puzzle ID",
    tags=["Crosswords"],
)
def get_crossword_by_id(
    client: NYTGamesClient = Depends(get_client),
    puzzle_id: int = Path(..., examples=[20759]),
) -> CrosswordPuzzle:
    """
    **Get a crossword by ID**

    Returns a crossword of any type by its puzzle ID, for example one of the
    two puzzles on a date that has two (see `/archive`).

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/crosswords/v6/puzzle/{puzzle_id}.json
    ```
    """
    return client.crossword_by_id(puzzle_id)


@router.get(
    "/crosswords/oracle/{publish_type}",
    response_model=CrosswordOracle,
    summary="Get the current and next Crossword puzzle",
    tags=["Crosswords"],
)
def get_crossword_oracle(
    client: NYTGamesClient = Depends(get_client),
    publish_type: CrosswordPublishType = Path(..., examples=["daily"]),
) -> CrosswordOracle:
    """
    **Get the current and next Crossword puzzle**

    Returns the puzzle ID, print date and publish time of the current and next
    puzzle for the publish type provided in the path parameter.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/crosswords/v2/oracle/{publish_type}.json
    ```
    """
    return client.crossword_oracle(publish_type)


class ExportFormat(str, enum.Enum):
    """Crossword file formats."""
    ipuz = "ipuz"
    puz = "puz"
    xml = "xml"


@router.get(
    "/crosswords/{publish_type}/{date}/download",
    summary="Download a crossword as a .puz, .ipuz or .xml file",
    tags=["Crosswords"],
    response_class=Response,
    responses={200: {"content": {media: {} for media in formats.MEDIA_TYPES.values()}},
               422: {"description": "The puzzle can't be saved in this format"}},
)
def download_crossword(
    publish_type: CrosswordPublishType,
    client: NYTGamesClient = Depends(get_client),
    date: str = Path(..., examples=["2025-06-12"]),
    file_format: ExportFormat = Query(ExportFormat.puz, alias="format"),
    progress: bool = Query(False, description="Include the user's saved progress (needs cookies)."),
) -> Response:
    """
    **Download a crossword file**

    Returns the crossword as Across Lite `.puz`, `.ipuz` or Crossword Compiler
    `.xml`, optionally with the user's saved progress. Some special puzzles
    can't be represented in these formats and return 422 with the reasons.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/crosswords/v6/puzzle/{publish_type}/{date}.json
    ```
    """
    puzzle = client.crossword(publish_type, date)
    game = client.crossword_game(puzzle.id, publish_type) if progress else None
    try:
        content = formats.export(puzzle, file_format.value, game)
    except formats.NYTGamesExportError as err:
        raise HTTPException(status_code=422, detail={"format": err.format, "reasons": err.reasons}) from None
    filename = f"nyt-{publish_type.value}-{puzzle.publicationDate}.{file_format.value}"
    return Response(content, media_type=formats.MEDIA_TYPES[file_format.value],
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# Crossword - Bonus
@router.get(
    "/crosswords/bonus/{date}",
    response_model=CrosswordPuzzle,
    summary="Get the Crossword Bonus puzzle for a specific date",
    tags=["Crosswords - Bonus"],
)
def get_crossword_bonus(
    client: NYTGamesClient = Depends(get_client),
    date: str = Path(..., examples=["1997-02-01"]),
) -> CrosswordPuzzle:
    """
    **Get a Crossword Bonus puzzle**

    Returns the Crossword Bonus puzzle for the date provided in the path parameter.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/crosswords/v6/puzzle/bonus/{date}.json
    ```
    """
    return client.crossword(CrosswordPublishType.bonus, date)


# Crossword - Daily
@router.get(
    "/crosswords/daily/today",
    response_model=CrosswordPuzzle,
    summary="Get the Crossword Daily puzzle for today",
    tags=["Crosswords - Daily"],
)
def get_crossword_puzzle_daily(
    client: NYTGamesClient = Depends(get_client),
) -> CrosswordPuzzle:
    """
    **Get the Crossword Daily puzzle for today**

    Returns the Crossword Daily puzzle for today.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/crosswords/v6/puzzle/daily.json
    ```
    """
    return client.crossword(CrosswordPublishType.daily)


@router.get(
    "/crosswords/daily/{date}",
    response_model=CrosswordPuzzle,
    summary="Get the Crossword Daily puzzle for a specific date",
    tags=["Crosswords - Daily"])
def get_crossword_puzzle(
    client: NYTGamesClient = Depends(get_client),
    date: str = Path(..., examples=["1993-11-21"]),
) -> CrosswordPuzzle:
    """
    **Get a Crossword Daily puzzle**

    Returns the Crossword Daily puzzle for the date provided in the path parameter.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/crosswords/v6/puzzle/daily/{date}.json
    ```
    """
    return client.crossword(CrosswordPublishType.daily, date)


# Crossword - Midi
@router.get(
    "/crosswords/midi/today",
    response_model=CrosswordPuzzle,
    summary="Get the Crossword Midi puzzle for today",
    tags=["Crosswords - Midi"]
)
def get_crossword_midi_daily(
    client: NYTGamesClient = Depends(get_client),
) -> CrosswordPuzzle:
    """
    **Get a Crossword Midi puzzle**

    Returns the Crossword Midi puzzle for today.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/crosswords/v6/puzzle/midi.json
    ```
    """
    return client.crossword(CrosswordPublishType.midi)


@router.get(
    "/crosswords/midi/{date}",
    response_model=CrosswordPuzzle,
    summary="Get the Crossword Midi puzzle for a specific date",
    tags=["Crosswords - Midi"])
def get_crossword_midi(
    client: NYTGamesClient = Depends(get_client),
    date: str = Path(..., examples=["2026-10-01"]),
) -> CrosswordPuzzle:
    """
    **Get a Crossword Midi puzzle**

    Returns the Crossword Midi puzzle for the date provided in the path parameter.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/crosswords/v6/puzzle/midi/{date}.json
    ```
    """
    return client.crossword(CrosswordPublishType.midi, date)


# Crossword - Mini
@router.get(
    "/crosswords/mini/today",
    response_model=CrosswordPuzzle,
    summary="Get the Crossword Mini puzzle for today",
    tags=["Crosswords - Mini"]
)
def get_crossword_mini_daily(
    client: NYTGamesClient = Depends(get_client),
) -> CrosswordPuzzle:
    """
    **Get a Crossword Mini puzzle**

    Returns the Crossword Mini puzzle for today.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/crosswords/v6/puzzle/mini.json
    ```
    """
    return client.crossword(CrosswordPublishType.mini)


@router.get(
    "/crosswords/mini/{date}",
    response_model=CrosswordPuzzle,
    summary="Get the Crossword Mini puzzle for a specific date",
    tags=["Crosswords - Mini"])
def get_crossword_mini(
    client: NYTGamesClient = Depends(get_client),
    date: str = Path(..., examples=["2025-06-12"]),
) -> CrosswordPuzzle:
    """
    **Get a Crossword Mini puzzle**

    Returns the Crossword Mini puzzle for the date provided in the path parameter.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/crosswords/v6/puzzle/mini/{date}.json
    ```
    """
    return client.crossword(CrosswordPublishType.mini, date)


@router.get(
    "/crosswords/puzzles",
    response_model=CrosswordPuzzlesList,
    summary="List Crossword Puzzles",
    tags=["Crosswords"],
)
def list_crossword_puzzles(
    client: NYTGamesClient = Depends(get_client),
    publish_type: Optional[CrosswordPublishType] = Query(None, examples=["daily"]),
    sort_order: Optional[str] = Query(None, examples=["asc"]),
    sort_by: Optional[str] = Query(None, examples=["print_date"]),
    date_start: Optional[str] = Query(None, examples=["2024-07-01"]),
    date_end: Optional[str] = Query(None, examples=["2024-07-31"])
) -> CrosswordPuzzlesList:
    """
    **List Crossword Puzzles**

    Returns a list of Crossword Puzzles based on the url parameters.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/crosswords/v3/puzzles.json
    ```
    """
    try:
        return client.crossword_puzzles(
            publish_type=publish_type,
            sort_order=sort_order,
            sort_by=sort_by,
            date_start=date_start,
            date_end=date_end,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from None


# Letter Boxed
@router.get(
    "/letter-boxed/{date}",
    response_model=LetterBoxedPuzzle,
    summary="Get the Letter Boxed puzzle for a specific date",
    tags=["Letter Boxed"])
def get_letter_boxed_puzzle(
    client: NYTGamesClient = Depends(get_client),
    date: str = Path(..., examples=["2026-10-03"]),
) -> LetterBoxedPuzzle:
    """
    **Get a Letter Boxed puzzle**

    Returns the Letter Boxed puzzle for the date provided in the path parameter.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/letter-boxed/v1/{date}.json
    ```
    """
    return client.letter_boxed(date)


# Player
@router.get(
    "/player/stats",
    response_model=Player,
    summary="Get the user's stats for every game",
    tags=["Player"])
def get_player_stats(
    client: NYTGamesClient = Depends(get_client),
) -> Player:
    """
    **Get player stats**

    Returns the user's stats for every game they have played (Wordle,
    Connections, Strands, Spelling Bee and the Daily, Mini and Midi
    crosswords). Requires the `NYT-S` cookie.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/games/state/wordleV2/latests?puzzle_ids=0
    ```
    """
    return client.player_stats()


# Spelling Bee
@router.get(
    "/spelling-bee",
    response_model=SpellingBeeGameData,
    summary="Get current Spelling Bee data",
    tags=["Spelling Bee"])
def get_spelling_bee(
    client: NYTGamesClient = Depends(get_client),
) -> SpellingBeeGameData:
    """
    **Get Current Spelling Bee Data**

    Returns the current Spelling Bee puzzles scraped from the game page.

    **Backend API**
    ```
    GET https://www.nytimes.com/puzzles/spelling-bee
    ```
    """
    return client.spelling_bee()


@router.get(
    "/spelling-bee/latest",
    response_model=SpellingBeeLatest,
    summary="List latest Spelling Bee puzzles",
    tags=["Spelling Bee"])
def get_spelling_bee_latest(
    client: NYTGamesClient = Depends(get_client),
    puzzle_ids: str = Query(None, examples=["1,2,3,4,5,6,7"]),
) -> SpellingBeeLatest:
    """
    **List latest Spelling Bee puzzles**

    Returns a list of Spelling Bee puzzles based on the url parameters.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/games/state/spelling_bee/latests
    ```
    """
    return client.spelling_bee_latest(puzzle_ids)


@router.get(
    "/spelling-bee/{date}",
    response_model=SpellingBeeGameDay,
    summary="Get the Spelling Bee puzzle for a specific date",
    tags=["Spelling Bee"])
def get_spelling_bee_puzzle(
    client: NYTGamesClient = Depends(get_client),
    date: str = Path(..., examples=["2026-10-03"]),
) -> SpellingBeeGameDay:
    """
    **Get a Spelling Bee puzzle**

    Returns the Spelling Bee puzzle for the date provided in the path parameter,
    in the same format as the game page. Puzzles are available from 2018-05-06.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/spelling-bee/v1/{date}.json
    ```
    """
    return client.spelling_bee_puzzle(date)


@router.get(
    "/spelling-bee/{date}/hints",
    summary="Get the Spelling Bee hints for a specific date",
    tags=["Spelling Bee"])
def get_spelling_bee_puzzle_hints(
    client: NYTGamesClient = Depends(get_client),
    date: str = Path(..., examples=["2026-10-03"]),
) -> dict:
    """
    **Get Spelling Bee hints**

    Returns Spelling Bee Forum style hints (word counts by first letter and
    length, two-letter starts, pangrams and points) for the date provided in
    the path parameter. Puzzles are available from 2018-05-06.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/spelling-bee/v1/{date}.json
    ```
    """
    return spelling_bee_hints(get_spelling_bee_puzzle(client, date))


# Strands
@router.get(
    "/strands/latest",
    response_model=StrandsLatest,
    summary="List latest Strands puzzles",
    tags=["Strands"])
def list_latest_strands_puzzles(
    client: NYTGamesClient = Depends(get_client),
    puzzle_ids: str = Query(None, examples=["1,2,3,4,5,6,7"]),
) -> StrandsLatest:
    """
    **List latest Strands puzzles**

    Returns the user's saved Strands games for the puzzle IDs in the url
    parameters. Requires the `NYT-S` cookie.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/games/state/strands/latests
    ```
    """
    return client.strands_latest(puzzle_ids)


@router.get(
    "/strands/{date}",
    response_model=StrandsPuzzle,
    summary="Get the Strands puzzle for a specific date",
    tags=["Strands"])
def get_strands_puzzle(
    client: NYTGamesClient = Depends(get_client),
    date: str = Path(..., examples=["2024-03-04"]),
) -> StrandsPuzzle:
    """
    **Get a Strands puzzle**

    Returns the Strands puzzle for the date provided in the path parameter.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/strands/v2/{date}.json
    ```
    """
    return client.strands(date)


# Wordle
@router.get(
    "/wordle/latest",
    response_model=WordlePuzzlesList,
    summary="List latest Wordle puzzles",
    tags=["Wordle"])
def list_latest_wordle_puzzles(
    client: NYTGamesClient = Depends(get_client),
    puzzle_ids: str = Query(None, examples=["1,2,3,4,5,6,7"]),
) -> WordlePuzzlesList:
    """
    **List latest Wordle puzzles**

    Returns a list of Wordle puzzles based on the url parameters.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/games/state/wordleV2/latests
    ```
    """
    return client.wordle_latest(puzzle_ids)


@router.get(
    "/wordle/{date}",
    response_model=WordlePuzzle,
    summary="Get the Wordle puzzle for a specific date",
    tags=["Wordle"])
def get_wordle_puzzle(
    client: NYTGamesClient = Depends(get_client),
    date: str = Path(..., examples=["2021-06-19"]),
) -> WordlePuzzle:
    """
    **Get a Wordle puzzle**

    Returns the Wordle puzzle for the date provided in the path parameter.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/wordle/v2/{date}.json
    ```
    """
    return client.wordle(date)


# WordleBot
@router.get(
    "/wordlebot",
    response_model=Optional[WordleBotAnalysis],
    summary="Get your WordleBot analysis of today's Wordle",
    tags=["WordleBot"])
def get_wordlebot(client: NYTGamesClient = Depends(get_client)) -> Optional[WordleBotAnalysis]:
    """
    **Get your WordleBot analysis**

    Returns your luck and skill for today's Wordle, overall and by round, or
    null if you haven't opened WordleBot today. Needs cookies. Only today's
    game is available.

    **Backend API**
    ```
    GET https://www.nytimes.com/svc/int/run/cubby/public-api/v1/responses/wordlebot/reader
    ```
    """
    return client.wordlebot()


@router.get(
    "/wordlebot/{date}/summary",
    response_model=WordleBotSummary,
    summary="Get WordleBot's summary of a day's Wordle",
    tags=["WordleBot"])
def get_wordlebot_summary(
    client: NYTGamesClient = Depends(get_client),
    date: str = Path(..., examples=["2026-10-04"]),
) -> WordleBotSummary:
    """
    **Get a WordleBot summary**

    Returns how everyone did on a day's Wordle: average guesses, skill and
    luck by mode, guess distributions, skill percentiles and the bot's solve
    paths (which include the solution). Available for every day.

    **Backend API**
    ```
    GET https://static01.nyt.com/newsgraphics/2022/wordlebot/{solution}-{date}/summary.json
    ```
    """
    return client.wordlebot_summary(date)


app = create_app()

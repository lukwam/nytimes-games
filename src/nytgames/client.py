"""NYT Games clients.

`NYTGamesClient` is synchronous and `AsyncNYTGamesClient` is its asyncio
twin: same methods, same arguments, same results, but awaited. Both run the
operations defined once in `_Operations`.
"""
import datetime
import functools
import inspect
import json
import re
from typing import Any
from typing import Iterable
from typing import Mapping

import httpx
from bs4 import BeautifulSoup

from nytgames import __version__
from nytgames.exceptions import NYTGamesNoProfileError
from nytgames.exceptions import NYTGamesNotFoundError
from nytgames.exceptions import NYTGamesParseError
from nytgames.models import ArchiveGame
from nytgames.models import ArchivePuzzle
from nytgames.models import BadgeGame
from nytgames.models import BonusPuzzleListing
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
from nytgames.models import SpellingBeePuzzle
from nytgames.models import StrandsLatest
from nytgames.models import StrandsPuzzle
from nytgames.models import TrophyCase
from nytgames.models import WordleBotAnalysis
from nytgames.models import WordleBotSummary
from nytgames.models import WordleInOneLatest
from nytgames.models import WordleInOnePuzzle
from nytgames.models import WordlePuzzle
from nytgames.models import WordlePuzzlesList
from nytgames.transport import NYT_BASE_URL
from nytgames.transport import Request
from nytgames.transport import Settings
from nytgames.transport import run_async
from nytgames.transport import run_sync

WORDLEBOT_URL = "https://www.nytimes.com/svc/int/run/cubby/public-api/v1/responses/wordlebot/reader"
WORDLEBOT_SUMMARY_URL = "https://static01.nyt.com/newsgraphics/2022/wordlebot/{solution}-{date}/summary.json"
# NYT's games archive returns at most 31 days per request.
ARCHIVE_DAYS = 31
BADGE_GAMES = tuple(game.value for game in BadgeGame)
USER_AGENT = f"nytimes-games/{__version__} (+https://github.com/lukwam/nytimes-games)"

Cookies = Mapping[str, str] | Iterable[Mapping[str, Any]] | str | None
PuzzleIds = int | str | Iterable[int | str] | None


def join_puzzle_ids(puzzle_ids: PuzzleIds) -> str | None:
    """Return puzzle IDs as the comma separated string NYT expects."""
    if puzzle_ids is None or isinstance(puzzle_ids, (int, str)):
        return None if puzzle_ids is None else str(puzzle_ids)
    return ",".join(str(puzzle_id) for puzzle_id in puzzle_ids)


COOKIE_NAME = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
COOKIE_VALUE_FORBIDDEN = re.compile(r"[\x00-\x1f\x7f;]")


def parse_cookies(cookies: Cookies) -> dict[str, str]:
    """Return cookies as a dict.

    Accepts a dict of cookie names to values, a list of cookie objects with
    `name` and `value` keys (the Cookie-Editor JSON export format), either of
    those as a JSON string, or a `Cookie` header string such as
    `"NYT-S=...; nyt-a=..."`.

    Raises ValueError for cookies that can't be sent, without including any
    cookie values in the message.
    """
    if not cookies:
        return {}
    if isinstance(cookies, str):
        text = cookies.strip()
        if text.startswith(("[", "{")):
            try:
                return parse_cookies(json.loads(text))
            except json.JSONDecodeError:
                raise ValueError("The cookies look like JSON but couldn't be read as JSON") from None
        parsed = {}
        for part in text.split(";"):
            name, sep, value = part.strip().partition("=")
            if sep:
                parsed[name.strip()] = value.strip()
        return check_cookies(parsed)
    if isinstance(cookies, Mapping):
        return check_cookies({str(k): str(v) for k, v in cookies.items()})
    try:
        return check_cookies({str(c["name"]): str(c["value"]) for c in cookies})
    except (KeyError, TypeError):
        raise ValueError("Cookie lists need a name and value for each cookie") from None


def check_cookies(cookies: dict[str, str]) -> dict[str, str]:
    """Raise ValueError if any cookie can't be sent in a Cookie header.

    The message names the cookie but never includes its value.
    """
    for name, value in cookies.items():
        if not COOKIE_NAME.match(name):
            raise ValueError("A cookie has an invalid name (cookie values aren't shown)")
        if COOKIE_VALUE_FORBIDDEN.search(value):
            raise ValueError(f"The {name} cookie's value has characters that can't be sent "
                             "(such as line breaks or semicolons); its value isn't shown")
    return cookies


def get_game_data(body: str | bytes) -> dict | None:
    """Get Game Data from Spelling Bee Page."""
    soup = BeautifulSoup(body, "html.parser")
    script_tag = soup.find("script", string=re.compile(r"window\.gameData\s*="))
    if script_tag:
        script_content = script_tag.string
        if script_content.startswith("window.gameData = {"):
            return json.loads(script_content[len("window.gameData = "):])
    return None


class _Operations:
    """Every request the clients make, written once as generators (see
    nytgames.transport). NYTGamesClient and AsyncNYTGamesClient run them."""

    def __init__(self, cookies: Cookies = None, user_agent: str = USER_AGENT, retries: int = 3,
                 backoff: float = 0.5, base_url: str = NYT_BASE_URL):
        self._settings = Settings(parse_cookies(cookies), user_agent, retries, backoff, base_url.rstrip("/"))

    @property
    def cookies(self) -> dict[str, str]:
        """The cookies the client sends to NYT, parsed into a dict."""
        return self._settings.cookies

    # Archive
    def archive(
        self,
        game: ArchiveGame | str,
        date_start: str,
        date_end: str,
    ) -> list[ArchivePuzzle]:
        """Return the puzzles published between two dates (YYYY-MM-DD), inclusive.

        `game` is connections, strands, wordle, crossword_daily, crossword_mini
        or crossword_midi. Each puzzle has its ID and print date, so this is the
        quickest way to find puzzle IDs for the game state methods. Doesn't
        need cookies. Future dates are not included.

        A few dates have two puzzles (such as 2022-12-31's daily and its 50x50
        Supermega); both are returned, so print dates can repeat.

        NYT returns at most 31 puzzles per request, so ranges are fetched 31
        days at a time, and a window that hits the limit is split and fetched
        again so no date is dropped.
        """
        game = ArchiveGame(game).value
        start = datetime.date.fromisoformat(date_start)
        end = datetime.date.fromisoformat(date_end)
        puzzles: dict[int, ArchivePuzzle] = {}
        while start <= end:
            window_end = min(start + datetime.timedelta(days=ARCHIVE_DAYS - 1), end)
            for puzzle in (yield from _Operations._archive_window(self, game, start, window_end)):
                puzzles.setdefault(puzzle.id, puzzle)
            start = window_end + datetime.timedelta(days=1)
        return sorted(puzzles.values(), key=lambda puzzle: (puzzle.print_date, puzzle.id))

    def _archive_window(self, game: str, start: datetime.date, end: datetime.date) -> list[ArchivePuzzle]:
        """Fetch one window, splitting it if NYT's 31 puzzle limit may have cut it short."""
        response = (yield Request(f"/svc/games/v1/archive/{game}/{start}/{end}"))
        if len(response) < ARCHIVE_DAYS or start == end:
            return [ArchivePuzzle(**puzzle) for puzzle in response]
        middle = start + (end - start) // 2
        return ((yield from _Operations._archive_window(self, game, start, middle))
                + (yield from _Operations._archive_window(self, game, middle + datetime.timedelta(days=1), end)))

    # Badges
    def trophy_case(self, game: BadgeGame | str) -> TrophyCase:
        """Return every badge for a game, earned or not, with your progress.

        `game` is wordleV2, connections, strands or spelling_bee. Requires
        the NYT-S cookie. This is the NYT Games app's trophy case; the saved
        game state methods only include the three badges on your shelf.
        """
        game = BadgeGame(game).value
        return TrophyCase(**(yield Request(f"/svc/games/badges/trophy-case/{game}")))

    def badges(self, games: Iterable[BadgeGame | str] = BADGE_GAMES) -> TrophyCase:
        """Return every badge for each game (default: all four), in one
        TrophyCase keyed by game. Makes one request per game.

        Names, descriptions and artwork are in each badge's `info`.
        """
        result = TrophyCase()
        for game in games:
            case = (yield from _Operations.trophy_case(self, game))
            result.user_id = result.user_id or case.user_id
            result.trophies.update(case.trophies)
        return result

    # Bonus Puzzles
    def bonus_week(self, date: str) -> BonusWeek:
        """Return the week's Bonus Puzzles drop that includes a date (YYYY-MM-DD).

        Drops come out on Wednesdays, starting 2026-08-26 (earlier dates
        return that first week), and NYT serves the next week's drop early.
        """
        response = (yield Request(f"/svc/games/bonus/week/v1/{date}.json"))
        if not isinstance(response, dict) or not isinstance(response.get("bonus_puzzles_week"), dict):
            raise NYTGamesParseError("NYT's bonus week response has no bonus_puzzles_week")
        return BonusWeek(**response["bonus_puzzles_week"])

    def bonus_weeks(self, date_start: str, date_end: str) -> list[BonusWeek]:
        """Return each week's Bonus Puzzles drop between two dates, oldest
        first, up to the latest published week. Makes one request per week."""
        weeks = [(yield from _Operations.bonus_week(self, date_start))]
        while True:
            next_drop = weeks[-1].next_drop
            if not next_drop or next_drop > date_end or next_drop <= weeks[-1].drop_date:
                return weeks
            try:
                week = (yield from _Operations.bonus_week(self, next_drop))
            except NYTGamesNotFoundError:  # not published yet
                return weeks
            if week.drop_date <= weeks[-1].drop_date:
                return weeks
            weeks.append(week)

    def bonus_puzzle(self, listing: BonusPuzzleListing):
        """Return a bonus puzzle from its listing in a BonusWeek: a
        WordleInOnePuzzle, ConnectionsPuzzle, StrandsPuzzle or CrosswordPuzzle."""
        fetch = {"wordle-in-one": _Operations.wordle_in_one, "connections": _Operations.connections_bonus,
                 "strands": _Operations.strands_bonus}.get(listing.game)
        if fetch:
            return (yield from fetch(self, listing.slug))
        if listing.game == "crossword":
            return (yield from _Operations.crossword_by_id(self, listing.id))
        raise ValueError(f"Unknown bonus puzzle game: {listing.game}")

    def wordle_in_one(self, slug: str) -> WordleInOnePuzzle:
        """Return a Wordle in 1 bonus puzzle by its slug (e.g. 2026-10-07-8)."""
        return WordleInOnePuzzle(**(yield Request(f"/svc/wordle-in-one/v1/bonus/{slug}.json")))

    def connections_bonus(self, slug: str) -> ConnectionsPuzzle:
        """Return a Connections bonus puzzle (Connections 3x3) by its slug."""
        return ConnectionsPuzzle(**(yield Request(f"/svc/connections/v2/bonus/{slug}.json")))

    def strands_bonus(self, slug: str) -> StrandsPuzzle:
        """Return a Strands bonus puzzle (Colorful Strands) by its slug."""
        return StrandsPuzzle(**(yield Request(f"/svc/strands/v2/bonus/{slug}.json")))

    def wordle_in_one_latest(self, puzzle_ids: PuzzleIds = None) -> WordleInOneLatest:
        """Return the user's saved Wordle in 1 games.

        `puzzle_ids` is a puzzle ID (the listing's `id`), a comma separated
        string or a list of up to 30 IDs. `states` only includes puzzles the
        user has played.
        """
        response = (yield Request(
            "/svc/games/state/wordle_in_one/latests",
            params={"puzzle_ids": join_puzzle_ids(puzzle_ids)},
        ))
        return WordleInOneLatest(**response)

    # Connections
    def connections(self, date: str) -> ConnectionsPuzzle:
        """Return the Connections puzzle for a date (YYYY-MM-DD)."""
        return ConnectionsPuzzle(**(yield Request(f"/svc/connections/v2/{date}.json")))

    def connections_latest(self, puzzle_ids: PuzzleIds = None, bonus: bool = False) -> ConnectionsLatest:
        """Return the user's latest Connections game states.

        `puzzle_ids` is a puzzle ID, a comma separated string or a list of up
        to 30 IDs. `states` only includes puzzles the user has played. Set
        `bonus` for bonus puzzles (Connections 3x3).
        """
        game = "connections_bonus" if bonus else "connections"
        response = (yield Request(
            f"/svc/games/state/{game}/latests",
            params={"puzzle_ids": join_puzzle_ids(puzzle_ids)},
        ))
        return ConnectionsLatest(**response)

    # Crosswords
    def crossword(
        self,
        publish_type: CrosswordPublishType | str = CrosswordPublishType.daily,
        date: str | None = None,
    ) -> CrosswordPuzzle:
        """Return a crossword puzzle.

        `publish_type` is one of daily, mini, midi or bonus. Returns today's
        puzzle if `date` is not set (bonus puzzles require a date).
        """
        publish_type = CrosswordPublishType(publish_type).value
        path = f"/svc/crosswords/v6/puzzle/{publish_type}"
        path = f"{path}/{date}.json" if date else f"{path}.json"
        return CrosswordPuzzle(**(yield Request(path)))

    def crossword_by_id(self, puzzle_id: int | str) -> CrosswordPuzzle:
        """Return a crossword of any type by its puzzle ID.

        Use it for dates with more than one puzzle, where crossword(date)
        returns only one of them (archive() lists both).
        """
        return CrosswordPuzzle(**(yield Request(f"/svc/crosswords/v6/puzzle/{puzzle_id}.json")))

    def crossword_puzzles(
        self,
        publish_type: CrosswordPublishType | str | None = None,
        sort_order: str | None = None,
        sort_by: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
    ) -> CrosswordPuzzlesList:
        """Return a list of crossword puzzles, including the user's progress.

        `publish_type` is daily, mini or bonus. NYT returns at most 100 puzzles
        per request, and incomplete or empty results for long ranges, so use
        ranges of 90 days or less. NYT's list doesn't include Midi puzzles (it returns Daily
        puzzles instead), so `midi` raises ValueError; use
        archive("crossword_midi", ...) and crossword_game() for Midi puzzles.
        """
        if publish_type is not None:
            publish_type = CrosswordPublishType(publish_type).value
            if publish_type == CrosswordPublishType.midi.value:
                raise ValueError(
                    "NYT's crossword list doesn't include Midi puzzles; "
                    'use archive("crossword_midi", ...) and crossword_game() instead'
                )
        params = {
            "publish_type": publish_type,
            "sort_order": sort_order,
            "sort_by": sort_by,
            "date_start": date_start,
            "date_end": date_end,
        }
        return CrosswordPuzzlesList(**(yield Request("/svc/crosswords/v3/puzzles.json", params=params)))

    def crossword_game(
        self,
        puzzle_id: PuzzleIds,
        publish_type: CrosswordPublishType | str = CrosswordPublishType.daily,
    ) -> CrosswordGame:
        """Return the user's saved game state for one or more crossword puzzles.

        `puzzle_id` is a puzzle ID, a comma separated string or a list of up
        to 30 IDs. `states` only includes puzzles the user has played.
        """
        publish_type = CrosswordPublishType(publish_type).value
        response = (yield Request(
            f"/svc/games/state/crossword_{publish_type}/latests",
            params={"puzzle_ids": join_puzzle_ids(puzzle_id)},
        ))
        return CrosswordGame(**response)

    def crossword_oracle(
        self,
        publish_type: CrosswordPublishType | str = CrosswordPublishType.daily,
    ) -> CrosswordOracle:
        """Return the current and next crossword puzzle (daily, mini or midi)."""
        publish_type = CrosswordPublishType(publish_type).value
        return CrosswordOracle(**(yield Request(f"/svc/crosswords/v2/oracle/{publish_type}.json")))

    # Player
    def player_stats(self) -> Player:
        """Return the user's stats for every game they have played.

        Requires the NYT-S cookie. Includes the user's NYT user ID. Raises
        NYTGamesNoProfileError for accounts that have never played a game
        while signed in, which have no NYT Games profile yet.
        """
        response = (yield Request(
            "/svc/games/state/wordleV2/latests",
            params={"puzzle_ids": "0"},
        ))
        if not isinstance(response, dict) or not response.get("player"):
            raise NYTGamesNoProfileError(
                "This NYT account has no NYT Games profile yet; NYT creates one when the "
                "account first plays a game while signed in"
            )
        return Player(**response["player"])

    # Letter Boxed
    def letter_boxed(self, date: str) -> LetterBoxedPuzzle:
        """Return the Letter Boxed puzzle for a date (YYYY-MM-DD).

        Puzzles are available from 2018-12-17, and NYT also serves the next day
        or two ahead of time. A few early dates have no puzzle (2018-12-21 to
        2019-01-05 and 2019-01-25) and raise NYTGamesNotFoundError.
        """
        return LetterBoxedPuzzle(**(yield Request(f"/svc/letter-boxed/v1/{date}.json")))

    # Spelling Bee
    def spelling_bee(self) -> SpellingBeeGameData:
        """Return the current Spelling Bee data scraped from the game page.

        Raises ValueError if the page does not contain the game data.
        """
        page = (yield Request("/puzzles/spelling-bee", kind="text"))
        game_data = get_game_data(page)
        if game_data is None:
            raise NYTGamesParseError("Spelling Bee game data not found in the page")
        return SpellingBeeGameData(**game_data)

    def spelling_bee_puzzle(self, date: str) -> SpellingBeeGameDay:
        """Return the Spelling Bee puzzle for a date (YYYY-MM-DD).

        Puzzles are available from 2018-05-06, and NYT also serves the next
        day ahead of time. The result has the same shape as the game page
        puzzles from spelling_bee_puzzles(), including the full word list, so
        it works with spelling_bee_hints(). Dates without a puzzle raise
        NYTGamesNotFoundError.
        """
        response = (yield Request(f"/svc/spelling-bee/v1/{date}.json"))
        return SpellingBeePuzzle(**response).to_game_day()

    def spelling_bee_puzzles(self) -> dict[str, SpellingBeeGameDay]:
        """Return every Spelling Bee puzzle on the game page, keyed by print date.

        The page includes today's puzzle and the puzzles back to the start of
        last week (about two weeks). Older puzzles are not available.
        """
        game_data = (yield from _Operations.spelling_bee(self))
        past = game_data.pastPuzzles
        puzzles = [game_data.today, game_data.yesterday, *past.thisWeek, *past.lastWeek]
        return {puzzle.printDate: puzzle for puzzle in sorted(puzzles, key=lambda p: p.printDate)}

    def spelling_bee_latest(self, puzzle_ids: PuzzleIds = None) -> SpellingBeeLatest:
        """Return the user's latest Spelling Bee game states.

        `puzzle_ids` is a puzzle ID, a comma separated string or a list of up
        to 30 IDs (NYT returns HTTP 400 for more). With no IDs, `states` is
        empty.
        """
        response = (yield Request(
            "/svc/games/state/spelling_bee/latests",
            params={"puzzle_ids": join_puzzle_ids(puzzle_ids)},
        ))
        return SpellingBeeLatest(**response)

    # Strands
    def strands(self, date: str) -> StrandsPuzzle:
        """Return the Strands puzzle for a date (YYYY-MM-DD)."""
        return StrandsPuzzle(**(yield Request(f"/svc/strands/v2/{date}.json")))

    def strands_latest(self, puzzle_ids: PuzzleIds = None, bonus: bool = False) -> StrandsLatest:
        """Return the user's latest Strands game states.

        `puzzle_ids` is a puzzle ID, a comma separated string or a list of up
        to 30 IDs. `states` only includes puzzles the user has played. Set
        `bonus` for bonus puzzles (Colorful Strands).
        """
        game = "strands_bonus" if bonus else "strands"
        response = (yield Request(
            f"/svc/games/state/{game}/latests",
            params={"puzzle_ids": join_puzzle_ids(puzzle_ids)},
        ))
        return StrandsLatest(**response)

    # Wordle
    def wordlebot(self) -> WordleBotAnalysis | None:
        """Return your WordleBot analysis of today's Wordle, or None.

        Needs cookies. NYT only keeps today's game, and only after you've
        opened WordleBot; earlier games aren't available. When there are
        several (one each time you open WordleBot), the latest is returned.
        """
        entries = (yield Request(WORDLEBOT_URL))
        analyses = [
            WordleBotAnalysis(**entry["content"], created_at=entry.get("created_at"),
                              response_id=entry.get("response_id"))
            for entry in entries
            if isinstance(entry.get("content"), dict) and entry["content"].get("guesses")
        ]
        return max(analyses, key=lambda a: a.created_at or "", default=None)

    def wordlebot_summary(self, date: str, solution: str | None = None) -> WordleBotSummary:
        """Return WordleBot's summary of how everyone did on a day's Wordle.

        Available for every day since the first Wordle (2021-06-19). The files
        are named by solution, so this also fetches the day's Wordle unless
        `solution` is given. Doesn't need cookies.
        """
        solution = solution or (yield from _Operations.wordle(self, date)).solution
        return WordleBotSummary(**(yield Request(WORDLEBOT_SUMMARY_URL.format(solution=solution, date=date))))

    def wordle(self, date: str) -> WordlePuzzle:
        """Return the Wordle puzzle for a date (YYYY-MM-DD)."""
        return WordlePuzzle(**(yield Request(f"/svc/wordle/v2/{date}.json")))

    def wordle_latest(self, puzzle_ids: PuzzleIds = None) -> WordlePuzzlesList:
        """Return the user's latest Wordle game states.

        `puzzle_ids` is a puzzle ID, a comma separated string or a list of IDs.
        """
        response = (yield Request(
            "/svc/games/state/wordleV2/latests",
            params={"puzzle_ids": join_puzzle_ids(puzzle_ids)},
        ))
        return WordlePuzzlesList(**response)


class NYTGamesClient(_Operations):
    """Client for the NYT Games APIs.

    Puzzles need no cookies. Your stats and saved games need the `NYT-S`
    cookie from a logged in nytimes.com browser session, in any form
    `parse_cookies` accepts. Cookies are only sent to www.nytimes.com (or
    `base_url`), never to other hosts such as static01.nyt.com.

    HTTP errors from NYT are raised as NYTGamesHTTPError:
    NYTGamesAuthenticationError for 401 and 403, NYTGamesNotFoundError for
    404 and NYTGamesRateLimitError for 429.

    Failed connections, rate limits (429) and NYT server errors (500, 502,
    503, 504) are retried up to `retries` times with exponential backoff
    (`backoff` seconds, doubling each time), honoring NYT's Retry-After
    header. Pass your own `httpx.Client` as `http_client` to control
    transport details, such as caching; it's used as is (with these retries)
    and not closed by `close()`.
    """

    def __init__(
        self,
        cookies: Cookies = None,
        http_client: httpx.Client | None = None,
        timeout: float = 30,
        user_agent: str = USER_AGENT,
        retries: int = 3,
        backoff: float = 0.5,
        base_url: str = NYT_BASE_URL,
    ):
        super().__init__(cookies, user_agent, retries, backoff, base_url)
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout, follow_redirects=True)

    def close(self) -> None:
        """Close the httpx client, unless you passed in your own."""
        if self._owns_http:
            self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class AsyncNYTGamesClient(_Operations):
    """Asyncio client for the NYT Games APIs: the same methods as
    `NYTGamesClient`, awaited.

        async with AsyncNYTGamesClient(cookies=...) as client:
            puzzle = await client.wordle("2026-10-11")

    Errors and retries are the same as `NYTGamesClient`'s. Pass your own
    `httpx.AsyncClient` as `http_client` to control transport details; it's
    used as is (with these retries) and not closed by `aclose()`.
    """

    def __init__(
        self,
        cookies: Cookies = None,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 30,
        user_agent: str = USER_AGENT,
        retries: int = 3,
        backoff: float = 0.5,
        base_url: str = NYT_BASE_URL,
    ):
        super().__init__(cookies, user_agent, retries, backoff, base_url)
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    async def aclose(self) -> None:
        """Close the httpx client, unless you passed in your own."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()


def _public_operations():
    for name, value in vars(_Operations).items():
        if not name.startswith("_") and inspect.isgeneratorfunction(value):
            yield name, value


def _sync_method(operation):
    @functools.wraps(operation)
    def method(self, *args, **kwargs):
        return run_sync(self._http, self._settings, operation(self, *args, **kwargs))
    return method


def _async_method(operation):
    @functools.wraps(operation)
    async def method(self, *args, **kwargs):
        return await run_async(self._http, self._settings, operation(self, *args, **kwargs))
    return method


for _name, _operation in _public_operations():
    setattr(NYTGamesClient, _name, _sync_method(_operation))
    setattr(AsyncNYTGamesClient, _name, _async_method(_operation))

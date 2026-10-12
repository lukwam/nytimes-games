"""Client tests, end to end over mocked HTTP.

Every client test runs against both NYTGamesClient and AsyncNYTGamesClient,
so they run offline and need no NYT cookies. Puzzle responses are real NYT
responses from tests/fixtures; saved games and stats are made up.
"""
import inspect
import json

import httpx
import pytest

import nytgames
from nytgames import AsyncNYTGamesClient
from nytgames import NYTGamesClient
from nytgames import NYTGamesHTTPError
from nytgames import NYTGamesNoProfileError
from nytgames import NYTGamesNotFoundError
from nytgames import NYTGamesParseError
from nytgames import parse_cookies
from nytgames.models import CrosswordPuzzle
from nytgames.models import LetterBoxedPuzzle
from nytgames.models import WordleBotSummary
from nytgames.models import WordlePuzzle
from tests.support import COOKIES
from tests.support import NYT
from tests.support import USER_ID
from tests.support import load
from tests.support import text

WORDLE_URL = f"{NYT}/svc/wordle/v2/2025-06-12.json"
SUMMARY_URL = "https://static01.nyt.com/newsgraphics/2022/wordlebot/vixen-2025-06-12/summary.json"
COOKIE_HEADER = "; ".join(f"{k}={v}" for k, v in COOKIES.items())


def params(route) -> dict:
    return dict(route.calls.last.request.url.params)


# Cookies

@pytest.mark.parametrize("cookies", [
    {"NYT-S": "abc", "nyt-a": "def"},
    [{"name": "NYT-S", "value": "abc", "domain": ".nytimes.com"}, {"name": "nyt-a", "value": "def"}],
    "NYT-S=abc; nyt-a=def",
])
def test_parse_cookies(cookies):
    """Cookies can be a dict, a Cookie-Editor JSON export or a header string."""
    assert parse_cookies(cookies) == {"NYT-S": "abc", "nyt-a": "def"}


def test_parse_cookies_empty():
    """No cookies is an empty dict."""
    assert parse_cookies(None) == {}


@pytest.mark.parametrize("cookies", [
    json.dumps([{"domain": ".nytimes.com", "name": "NYT-S", "value": "abc="}, {"name": "nyt-a", "value": "def"}],
               indent=2),
    '{"NYT-S": "abc=", "nyt-a": "def"}',
])
def test_parse_cookies_json_strings(cookies):
    """A Cookie-Editor JSON export or a JSON object works as a string too."""
    assert parse_cookies(cookies) == {"NYT-S": "abc=", "nyt-a": "def"}


@pytest.mark.parametrize("cookies", [
    {"NYT-S": "SECRET\nVALUE"},
    {"NYT-S": "SECRET;VALUE"},
    {"bad name": "SECRETVALUE"},
    '[{"name": "NYT-S", "value": "SECRETVALUE"',
])
def test_bad_cookies_never_show_their_values(make, cookies):
    """Cookies that can't be sent raise ValueError without the value in the message."""
    with pytest.raises(ValueError) as info:
        make(cookies=cookies)
    assert "SECRET" not in str(info.value)


def test_cookies_property(make):
    """The parsed cookies are available on the client."""
    assert make(cookies="NYT-S=abc; nyt-a=def").client.cookies == {"NYT-S": "abc", "nyt-a": "def"}
    assert make().client.cookies == {}


async def test_cookies_are_sent_to_nytimes(make, mock):
    """Cookies, in any form parse_cookies accepts, are sent to www.nytimes.com."""
    route = mock.get(WORDLE_URL).respond(json=load("wordle/2025-06-12.json"))
    puzzle = await make(cookies="NYT-S=abc")("wordle", "2025-06-12")
    assert puzzle.solution == "vixen"
    assert route.calls.last.request.headers["Cookie"] == "NYT-S=abc"


async def test_cookies_are_never_sent_to_other_hosts(logged_in, mock):
    """wordlebot_summary fetches the Wordle (with cookies), then NYT's static file (without)."""
    wordle = mock.get(WORDLE_URL).respond(json=load("wordle/2025-06-12.json"))
    summary = mock.get(SUMMARY_URL).respond(json=load("wordlebot/summary_vixen_2025-06-12.json"))
    assert isinstance(await logged_in("wordlebot_summary", "2025-06-12"), WordleBotSummary)
    assert wordle.calls.last.request.headers["Cookie"] == COOKIE_HEADER
    assert summary.call_count == 1
    assert "Cookie" not in summary.calls.last.request.headers


async def test_no_cookie_header_without_cookies(api, mock):
    route = mock.get(WORDLE_URL).respond(json=load("wordle/2025-06-12.json"))
    await api("wordle", "2025-06-12")
    assert "Cookie" not in route.calls.last.request.headers


# Requests

async def test_wordle(api, mock):
    route = mock.get(WORDLE_URL).respond(json=load("wordle/2025-06-12.json"))
    puzzle = await api("wordle", "2025-06-12")
    assert isinstance(puzzle, WordlePuzzle)
    assert puzzle.solution == "vixen" and puzzle.print_date == "2025-06-12"
    request = route.calls.last.request
    assert request.headers["Accept"] == "application/json"
    assert request.headers["User-Agent"].startswith(f"nytimes-games/{nytgames.__version__}")


async def test_custom_user_agent(make, mock):
    route = mock.get(WORDLE_URL).respond(json=load("wordle/2025-06-12.json"))
    await make(user_agent="my-bot/1.0")("wordle", "2025-06-12")
    assert route.calls.last.request.headers["User-Agent"] == "my-bot/1.0"


async def test_base_url(make, mock):
    """Requests go to base_url (a trailing slash is fine), which gets the cookies;
    full URLs such as static01.nyt.com's still don't."""
    route = mock.get("https://nyt.example/svc/wordle/v2/2025-06-12.json").respond(
        json=load("wordle/2025-06-12.json"))
    summary = mock.get(SUMMARY_URL).respond(json=load("wordlebot/summary_vixen_2025-06-12.json"))
    await make(base_url="https://nyt.example/", cookies=COOKIES)("wordlebot_summary", "2025-06-12")
    assert route.call_count == 1
    assert route.calls.last.request.headers["Cookie"] == COOKIE_HEADER
    assert summary.call_count == 1
    assert "Cookie" not in summary.calls.last.request.headers


async def test_http_errors_are_raised(api, mock):
    """HTTP errors from NYT are NYTGamesHTTPErrors with the status and the response."""
    mock.get(f"{NYT}/svc/wordle/v2/1900-01-01.json").respond(404)
    with pytest.raises(NYTGamesNotFoundError) as info:
        await api("wordle", "1900-01-01")
    assert isinstance(info.value, NYTGamesHTTPError)
    assert info.value.status_code == 404
    assert isinstance(info.value.response, httpx.Response)
    assert info.value.response.status_code == 404


# Crosswords

@pytest.mark.parametrize("publish_type,date,path", [
    ("daily", None, "/svc/crosswords/v6/puzzle/daily.json"),
    ("daily", "2025-06-12", "/svc/crosswords/v6/puzzle/daily/2025-06-12.json"),
    ("mini", "2025-06-12", "/svc/crosswords/v6/puzzle/mini/2025-06-12.json"),
    ("midi", None, "/svc/crosswords/v6/puzzle/midi.json"),
    ("bonus", "1997-02-01", "/svc/crosswords/v6/puzzle/bonus/1997-02-01.json"),
])
async def test_crossword_url(api, mock, publish_type, date, path):
    """Crossword puzzles are fetched from the v6 endpoint for each type."""
    route = mock.get(f"{NYT}{path}").respond(json=load("crossword/mini_2025-06-12.json"))
    puzzle = await api("crossword", publish_type, date)
    assert isinstance(puzzle, CrosswordPuzzle) and puzzle.id == 22900
    assert route.call_count == 1


async def test_crossword_rejects_unknown_type(api, mock):
    """Unknown publish types raise ValueError before calling NYT."""
    with pytest.raises(ValueError):
        await api("crossword", "weekly")
    assert not mock.calls


async def test_crossword_by_id(api, mock):
    route = mock.get(f"{NYT}/svc/crosswords/v6/puzzle/22900.json").respond(
        json=load("crossword/mini_2025-06-12.json"))
    assert (await api("crossword_by_id", 22900)).id == 22900
    assert route.call_count == 1


async def test_crossword_oracle(api, mock):
    mock.get(f"{NYT}/svc/crosswords/v2/oracle/daily.json").respond(json=load("crossword/oracle_daily.json"))
    oracle = await api("crossword_oracle")
    assert oracle.model_dump()["results"]["current"]["puzzle_id"] == 24534


async def test_unset_params_are_not_sent(api, mock):
    """Params that are not set are left out of the request."""
    route = mock.get(f"{NYT}/svc/crosswords/v3/puzzles.json").respond(json={"results": [], "status": "OK"})
    await api("crossword_puzzles", publish_type="mini", date_start="2026-10-01")
    assert params(route) == {"publish_type": "mini", "date_start": "2026-10-01"}


async def test_crossword_puzzles_rejects_midi(api, mock):
    """NYT's list returns Daily puzzles for Midi, so the client refuses to ask."""
    with pytest.raises(ValueError, match="Midi"):
        await api("crossword_puzzles", "midi")
    assert not mock.calls


async def test_crossword_puzzles_null_results_are_empty(api, mock):
    """NYT returns null results for empty or too long ranges."""
    mock.get(f"{NYT}/svc/crosswords/v3/puzzles.json").respond(json={"status": "OK", "results": None})
    assert (await api("crossword_puzzles", "daily", date_start="2030-01-01")).results == []


@pytest.mark.parametrize("puzzle_ids,expected", [
    (24287, "24287"),
    ("1,2", "1,2"),
    ([1, "2", 3], "1,2,3"),
])
async def test_puzzle_ids_accept_lists(logged_in, mock, puzzle_ids, expected):
    """Game state methods accept one ID, a comma separated string or a list."""
    route = mock.get(f"{NYT}/svc/games/state/crossword_daily/latests").respond(
        json={"user_id": USER_ID, "states": []})
    await logged_in("crossword_game", puzzle_ids)
    assert params(route) == {"puzzle_ids": expected}


@pytest.mark.parametrize("label,expected", [("12", 12), ("CW", "CW"), ("↙", "↙"), (None, None)])
def test_crossword_cell_labels(label, expected):
    """Cell labels are numbers, except on special puzzles that use text."""
    from nytgames.models import CrosswordPuzzleCell
    cell = CrosswordPuzzleCell(**({} if label is None else {"label": label}))
    assert cell.label == expected


def test_crossword_clue_without_label():
    """Special clues, such as an "Around" clue, can have no label."""
    from nytgames.models import CrosswordPuzzleClue
    clue = CrosswordPuzzleClue(cells=[1, 2], direction="Around", text=[{"plain": "Self-descriptive"}])
    assert clue.label is None


# Archive

async def test_archive_keeps_game_specific_fields(api, mock):
    route = mock.get(f"{NYT}/svc/games/v1/archive/wordle/2025-06-10/2025-06-12").respond(
        json=load("archive/wordle_2025-06-10_2025-06-12.json"))
    puzzles = await api("archive", "wordle", "2025-06-10", "2025-06-12")
    assert route.call_count == 1
    assert [p.print_date for p in puzzles] == ["2025-06-10", "2025-06-11", "2025-06-12"]
    assert puzzles[-1].id == 919
    assert puzzles[-1].model_dump()["solution"] == "vixen"


async def test_archive_fetches_31_days_at_a_time(api, mock):
    """The games archive allows 31 days per request, so longer ranges are split."""
    archive = f"{NYT}/svc/games/v1/archive/crossword_midi"
    routes = [
        mock.get(f"{archive}/2026-01-01/2026-01-31").respond(json=[{"id": 1, "print_date": "2026-01-01"}]),
        mock.get(f"{archive}/2026-02-01/2026-03-03").respond(json=[{"id": 2, "print_date": "2026-02-01"}]),
        mock.get(f"{archive}/2026-03-04/2026-03-04").respond(json=[{"id": 3, "print_date": "2026-03-04"}]),
    ]
    puzzles = await api("archive", "crossword_midi", "2026-01-01", "2026-03-04")
    assert [p.id for p in puzzles] == [1, 2, 3]
    assert [route.call_count for route in routes] == [1, 1, 1]
    assert len(mock.calls) == 3


async def test_archive_splits_windows_that_hit_the_limit(api, mock):
    """A window with 31 puzzles may be cut short, so it's split and fetched again."""
    def day(n):
        return f"2022-12-{n:02d}"

    def respond(request, start, end):
        first, last = int(start[-2:]), int(end[-2:])
        puzzles = [{"id": 100 + n, "print_date": day(n)} for n in range(first, last + 1)]
        if first <= 31 <= last:
            puzzles.append({"id": 999, "print_date": day(31)})  # a second puzzle on the 31st
        return httpx.Response(200, json=puzzles[-31:])  # NYT returns at most 31, dropping the earliest

    mock.get(url__regex=rf"^{NYT}/svc/games/v1/archive/crossword_daily/(?P<start>[\d-]+)/(?P<end>[\d-]+)$").mock(
        side_effect=respond)
    puzzles = await api("archive", "crossword_daily", "2022-12-01", "2022-12-31")
    assert len(puzzles) == 32
    assert puzzles[0].print_date == "2022-12-01"
    assert [p.id for p in puzzles if p.print_date == "2022-12-31"] == [131, 999]


async def test_archive_rejects_unknown_games(api, mock):
    with pytest.raises(ValueError):
        await api("archive", "spelling_bee", "2026-10-04", "2026-10-04")
    assert not mock.calls


# Other puzzles

async def test_letter_boxed(api, mock):
    """Letter Boxed puzzles are fetched from the v1 endpoint by date."""
    route = mock.get(f"{NYT}/svc/letter-boxed/v1/2025-06-12.json").respond(json=load("letter_boxed/2025-06-12.json"))
    puzzle = await api("letter_boxed", "2025-06-12")
    assert isinstance(puzzle, LetterBoxedPuzzle)
    assert puzzle.sides == ["ZAI", "BRL", "DUE", "TOV"]
    assert puzzle.model_dump()["is_free"] is True
    assert route.call_count == 1


async def test_connections(api, mock):
    mock.get(f"{NYT}/svc/connections/v2/2025-06-12.json").respond(json=load("connections/2025-06-12.json"))
    puzzle = await api("connections", "2025-06-12")
    assert puzzle.id == 765 and puzzle.categories[0].title == "GETTING COZY"
    assert puzzle.categories[0].cards[0].text == "CUDDLING"


async def test_connections_picture_puzzle(api, mock):
    """Picture puzzle cards have image fields instead of content."""
    image_card = {
        "position": 4,
        "image_url": "https://games-phoenix-assets-prd.s3.us-east-1.amazonaws.com/slot-machine.svg",
        "image_alt_text": "SLOT MACHINE",
    }
    mock.get(f"{NYT}/svc/connections/v2/2026-05-06.json").respond(json={
        "id": 1,
        "status": "OK",
        "print_date": "2026-05-06",
        "editor": "Wyna Liu",
        "illustrator": "Glenn Harvey",
        "categories": [{"title": "Things", "cards": [image_card, {"content": "BELL", "position": 0}]}],
    })
    puzzle = await api("connections", "2026-05-06")
    image, word = puzzle.categories[0].cards
    assert puzzle.illustrator == "Glenn Harvey"
    assert image.content is None
    assert image.image_alt_text == "SLOT MACHINE"
    assert image.text == "SLOT MACHINE"
    assert word.text == "BELL"


async def test_spelling_bee_page_is_read_as_html(api, mock):
    """Spelling Bee's game page is read as HTML, not JSON."""
    route = mock.get(f"{NYT}/puzzles/spelling-bee").respond(text=text("spelling_bee/page.html"))
    assert (await api("spelling_bee")).today.printDate == "2026-10-12"
    assert route.calls.last.request.headers.get("Accept") != "application/json"


# Player and saved games

async def test_player_stats(logged_in, mock):
    """Player stats are read from the game state service with puzzle_ids=0."""
    route = mock.get(f"{NYT}/svc/games/state/wordleV2/latests").respond(json={
        "user_id": USER_ID,
        "states": [],
        "player": {
            "user_id": USER_ID,
            "stats": {
                "connections": {
                    "current_streak": 150, "max_streak": 302, "mistakes": {"0": 1},
                    "puzzles_completed": 850, "puzzles_won": 840,
                },
                "wordle": {
                    "legacyStats": {
                        "currentStreak": 72, "gamesPlayed": 1260, "gamesWon": 1228,
                        "guesses": {"1": 2, "2": 39, "3": 314, "4": 484, "5": 281, "6": 108, "fail": 32},
                        "maxStreak": 144,
                    },
                    "calculatedStats": {"currentStreak": 3, "maxStreak": 144},
                },
                "crossplay": {"won": 0},
            },
        },
    })
    player = await logged_in("player_stats")
    assert player.user_id == USER_ID
    assert player.stats.connections.puzzles_won == 840
    assert player.stats.wordle.legacyStats.guesses.three == 314
    assert player.stats.wordle.calculatedStats.currentStreak == 3
    assert player.stats.strands is None
    assert player.stats.model_dump()["crossplay"] == {"won": 0}
    assert params(route) == {"puzzle_ids": "0"}
    assert route.calls.last.request.headers["Cookie"] == COOKIE_HEADER


@pytest.mark.parametrize("response", [
    {"user_id": USER_ID, "states": [], "badges_trophy_shelf": {}},
    {"user_id": USER_ID, "states": [], "player": None},
])
async def test_player_stats_without_games_profile(logged_in, mock, response):
    """Accounts that have never played have no player; that's a clear error, still a KeyError."""
    mock.get(f"{NYT}/svc/games/state/wordleV2/latests").respond(json=response)
    with pytest.raises(NYTGamesNoProfileError, match="no NYT Games profile"):
        await logged_in("player_stats")
    with pytest.raises(KeyError):
        await logged_in("player_stats")


async def test_wordle_latest_params(logged_in, mock):
    route = mock.get(f"{NYT}/svc/games/state/wordleV2/latests").respond(json={"user_id": USER_ID, "states": []})
    await logged_in("wordle_latest", [1, 2])
    assert params(route) == {"puzzle_ids": "1,2"}


async def test_spelling_bee_latest_without_player(logged_in, mock):
    mock.get(f"{NYT}/svc/games/state/spelling_bee/latests").respond(json={"user_id": USER_ID, "states": []})
    assert (await logged_in("spelling_bee_latest")).player is None


def test_older_game_state_shapes():
    """Older saved games omit fields, and some Wordles use a rounds-based format."""
    from nytgames.models import SpellingBeeLatest
    from nytgames.models import WordlePuzzlesList

    bee = SpellingBeeLatest(user_id=1, player={"user_id": 1}, states=[{
        "game": "spelling_bee", "print_date": "", "puzzle_id": "5", "user_id": 1,
        "game_data": {"answers": ["chin"], "isRevealed": False}}])
    assert bee.states[0].game_data.rank is None and bee.states[0].print_date == ""

    wordle = WordlePuzzlesList(user_id=1, states=[
        {"game": "wordleV2", "puzzle_id": "1", "user_id": 1, "timestamp": 0,
         "game_data": {"currentRoundIndex": 1, "puzzleComplete": True,
                       "rounds": [{"complete": True, "timeMs": 52000}]}},
        {"game": "wordleV2", "puzzle_id": "2", "user_id": 1, "timestamp": 0, "print_date": "",
         "game_data": {"boardState": ["crane"], "currentRowIndex": 1, "status": "WIN", "setLegacyStats": True}},
    ])
    rounds, board = (s.game_data for s in wordle.states)
    assert rounds.rounds_format and rounds.rounds[0].timeMs == 52000 and rounds.boardState == []
    assert not board.rounds_format and board.status == "WIN"


def test_old_stats_model_names_still_import():
    """Model names from v0.1.0 still work."""
    from nytgames.models import Player
    from nytgames.models import SpellingBeePlayer
    assert SpellingBeePlayer is Player


async def test_operations_that_call_others(logged_in, mock):
    """badges makes one trophy case request per game and merges them."""
    route = mock.get(url__regex=rf"^{NYT}/svc/games/badges/trophy-case/(?P<game>\w+)$").mock(
        side_effect=lambda request, game: httpx.Response(200, json={"user_id": USER_ID, "trophies": {game: {}}}))
    case = await logged_in("badges", ["wordleV2", "strands"])
    assert list(case.trophies) == ["wordleV2", "strands"]
    assert case.user_id == USER_ID
    assert [c.request.url.path for c in route.calls] == [
        "/svc/games/badges/trophy-case/wordleV2", "/svc/games/badges/trophy-case/strands"]


# Bonus puzzles

async def test_bonus_week_unexpected_response(api, mock):
    mock.get(f"{NYT}/svc/games/bonus/week/v1/2026-10-07.json").respond(json={"error": "nope"})
    with pytest.raises(NYTGamesParseError):
        await api("bonus_week", "2026-10-07")


async def test_errors_reach_operations(api, mock):
    """Errors are thrown into operations, so bonus_weeks can stop at an unpublished week."""
    mock.get(f"{NYT}/svc/games/bonus/week/v1/2026-10-07.json").respond(json=load("bonus/week_2026-10-07.json"))
    unpublished = mock.get(f"{NYT}/svc/games/bonus/week/v1/2026-10-14.json").respond(404)
    weeks = await api("bonus_weeks", "2026-10-07", "2026-12-31")
    assert [w.drop_date for w in weeks] == ["2026-10-07"]
    assert unpublished.call_count == 1


# Clients

def test_sync_and_async_clients_have_the_same_methods():
    def public(cls):
        return {n for n in dir(cls) if not n.startswith("_") and callable(getattr(cls, n))}
    assert public(NYTGamesClient) - {"close"} == public(AsyncNYTGamesClient) - {"aclose"}
    assert "close" in public(NYTGamesClient) and "aclose" in public(AsyncNYTGamesClient)
    for name in public(NYTGamesClient) - {"close"}:
        sync, async_ = getattr(NYTGamesClient, name), getattr(AsyncNYTGamesClient, name)
        assert sync.__doc__ and sync.__doc__ == async_.__doc__, name
        assert inspect.signature(sync) == inspect.signature(async_), name
        assert inspect.iscoroutinefunction(async_) and not inspect.iscoroutinefunction(sync), name
    assert "Wordle" in NYTGamesClient.wordle.__doc__


@pytest.mark.parametrize("cls", [NYTGamesClient, AsyncNYTGamesClient])
def test_timeout_is_passed_to_the_http_client(cls):
    client = cls(timeout=7)
    assert client._http.timeout == httpx.Timeout(7)
    assert client._http.follow_redirects
    assert cls()._http.timeout == httpx.Timeout(30)


def test_sync_client_lifecycle():
    with NYTGamesClient() as client:
        http = client._http
        assert isinstance(http, httpx.Client)
    assert http.is_closed
    own = httpx.Client()
    with NYTGamesClient(http_client=own) as client:
        assert client._http is own
    assert not own.is_closed  # yours to close
    NYTGamesClient(http_client=own).close()
    assert not own.is_closed
    own.close()


async def test_async_client_lifecycle():
    async with AsyncNYTGamesClient() as client:
        http = client._http
        assert isinstance(http, httpx.AsyncClient)
    assert http.is_closed
    own = httpx.AsyncClient()
    async with AsyncNYTGamesClient(http_client=own) as client:
        assert client._http is own
    assert not own.is_closed  # yours to close
    await AsyncNYTGamesClient(http_client=own).aclose()
    assert not own.is_closed
    await own.aclose()


async def test_your_own_http_client_is_used_as_is(make, mock):
    """Your own http_client's settings apply, alongside the client's headers."""
    route = mock.get(WORDLE_URL).respond(json=load("wordle/2025-06-12.json"))
    is_async = make().kind == "async"
    own = (httpx.AsyncClient if is_async else httpx.Client)(headers={"X-Mine": "yes"})
    api = make(http_client=own, cookies=COOKIES)
    assert api.client._http is own
    assert (await api("wordle", "2025-06-12")).solution == "vixen"
    headers = route.calls.last.request.headers
    assert headers["X-Mine"] == "yes"
    assert headers["Cookie"] == COOKIE_HEADER
    assert headers["User-Agent"].startswith("nytimes-games/")
    if is_async:
        await own.aclose()
    else:
        own.close()

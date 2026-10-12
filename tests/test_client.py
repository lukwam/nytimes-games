"""NYT Games client tests.

These tests mock the HTTP session, so they run offline and do not need NYT
cookies.
"""
import json
from unittest import mock

import pytest
import requests

from nytgames import NYTGamesClient
from nytgames import NYTGamesNoProfileError
from nytgames import NYTGamesParseError
from nytgames import parse_cookies


@pytest.fixture
def session():
    """Return a mock requests.Session."""
    session = mock.Mock(spec=requests.Session)
    response = session.get.return_value
    response.status_code = 200
    response.raise_for_status.return_value = None
    yield session
    # The library is read-only: every request any client test makes must be a GET.
    assert {call[0] for call in session.method_calls if not call[0].startswith("get().")} <= {"get"}


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


def test_cookies_are_sent(session):
    """Cookies are sent with every request."""
    session.get.return_value.json.return_value = {"id": 1, "solution": "cigar", "print_date": "2021-06-19"}
    client = NYTGamesClient(cookies="NYT-S=abc", session=session)
    puzzle = client.wordle("2021-06-19")
    assert puzzle.solution == "cigar"
    assert session.get.call_args.kwargs["cookies"] == {"NYT-S": "abc"}


@pytest.mark.parametrize("publish_type,date,path", [
    ("daily", None, "/svc/crosswords/v6/puzzle/daily.json"),
    ("daily", "2025-06-12", "/svc/crosswords/v6/puzzle/daily/2025-06-12.json"),
    ("mini", "2025-06-12", "/svc/crosswords/v6/puzzle/mini/2025-06-12.json"),
    ("midi", None, "/svc/crosswords/v6/puzzle/midi.json"),
    ("bonus", "1997-02-01", "/svc/crosswords/v6/puzzle/bonus/1997-02-01.json"),
])
def test_crossword_url(session, publish_type, date, path):
    """Crossword puzzles are fetched from the v6 endpoint for each type."""
    session.get.return_value.json.return_value = {
        "id": 1,
        "body": [],
        "constructors": [],
        "copyright": "",
        "lastUpdated": "",
        "publicationDate": "",
    }
    NYTGamesClient(session=session).crossword(publish_type, date)
    assert session.get.call_args.args[0] == f"https://www.nytimes.com{path}"


def test_crossword_rejects_unknown_type(session):
    """Unknown publish types raise ValueError before calling NYT."""
    with pytest.raises(ValueError):
        NYTGamesClient(session=session).crossword("weekly")
    session.get.assert_not_called()


def test_unset_params_are_not_sent(session):
    """Params that are not set are left out of the request."""
    session.get.return_value.json.return_value = {"results": [], "status": "OK"}
    NYTGamesClient(session=session).crossword_puzzles(publish_type="mini", date_start="2026-10-01")
    assert session.get.call_args.kwargs["params"] == {"publish_type": "mini", "date_start": "2026-10-01"}


def test_http_errors_are_raised(session):
    """HTTP errors from NYT are raised as requests.HTTPError."""
    session.get.return_value.raise_for_status.side_effect = requests.HTTPError("404")
    with pytest.raises(requests.HTTPError):
        NYTGamesClient(session=session).wordle("1900-01-01")


def test_letter_boxed(session):
    """Letter Boxed puzzles are fetched from the v1 endpoint by date."""
    session.get.return_value.json.return_value = {
        "id": 2860,
        "dictionary": ["LUMPY", "WHEREWITHAL"],
        "editor": "Sam Ezersky",
        "is_free": True,
        "ourSolution": ["WHEREWITHAL", "LUMPY"],
        "par": 4,
        "printDate": "2026-10-03",
        "sides": ["LHY", "MIE", "RUT", "WAP"],
    }
    puzzle = NYTGamesClient(session=session).letter_boxed("2026-10-03")
    assert puzzle.sides == ["LHY", "MIE", "RUT", "WAP"]
    assert puzzle.model_dump()["is_free"] is True
    assert session.get.call_args.args[0] == "https://www.nytimes.com/svc/letter-boxed/v1/2026-10-03.json"


@pytest.mark.parametrize("status,error", [
    (401, "NYTGamesAuthenticationError"),
    (403, "NYTGamesAuthenticationError"),
    (404, "NYTGamesNotFoundError"),
    (500, "NYTGamesHTTPError"),
])
def test_http_errors_are_typed(session, status, error):
    """HTTP errors are raised as NYTGames errors that are still requests.HTTPError."""
    import nytgames
    response = session.get.return_value
    response.status_code = status
    response.raise_for_status.side_effect = requests.HTTPError(str(status), response=response)
    with pytest.raises(getattr(nytgames, error)) as info:
        NYTGamesClient(session=session).wordle("2026-10-03")
    assert isinstance(info.value, requests.HTTPError)
    assert info.value.response.status_code == status


def test_user_agent_identifies_the_library(session):
    """Requests identify nytgames in the User-Agent."""
    import nytgames
    session.get.return_value.json.return_value = {"id": 1, "solution": "cigar", "print_date": "2021-06-19"}
    NYTGamesClient(session=session).wordle("2021-06-19")
    assert session.get.call_args.kwargs["headers"]["User-Agent"].startswith(f"nytimes-games/{nytgames.__version__}")


def test_player_stats(session):
    """Player stats are read from the game state service with puzzle_ids=0."""
    session.get.return_value.json.return_value = {
        "user_id": 123,
        "states": [],
        "player": {
            "user_id": 123,
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
    }
    player = NYTGamesClient(cookies="NYT-S=abc", session=session).player_stats()
    assert player.user_id == 123
    assert player.stats.connections.puzzles_won == 840
    assert player.stats.wordle.legacyStats.guesses.three == 314
    assert player.stats.wordle.calculatedStats.currentStreak == 3
    assert player.stats.strands is None
    assert player.stats.model_dump()["crossplay"] == {"won": 0}
    assert session.get.call_args.kwargs["params"] == {"puzzle_ids": "0"}


def test_old_stats_model_names_still_import():
    """Model names from v0.1.0 still work."""
    from nytgames.models import Player
    from nytgames.models import SpellingBeePlayer
    assert SpellingBeePlayer is Player


def test_connections_picture_puzzle(session):
    """Picture puzzle cards have image fields instead of content."""
    image_card = {
        "position": 4,
        "image_url": "https://games-phoenix-assets-prd.s3.us-east-1.amazonaws.com/slot-machine.svg",
        "image_alt_text": "SLOT MACHINE",
    }
    session.get.return_value.json.return_value = {
        "id": 1,
        "status": "OK",
        "print_date": "2026-05-06",
        "editor": "Wyna Liu",
        "illustrator": "Glenn Harvey",
        "categories": [{"title": "Things", "cards": [image_card, {"content": "BELL", "position": 0}]}],
    }
    puzzle = NYTGamesClient(session=session).connections("2026-05-06")
    image, word = puzzle.categories[0].cards
    assert puzzle.illustrator == "Glenn Harvey"
    assert image.content is None
    assert image.image_alt_text == "SLOT MACHINE"
    assert image.text == "SLOT MACHINE"
    assert word.text == "BELL"


@pytest.mark.parametrize("puzzle_ids,expected", [
    (24287, "24287"),
    ("1,2", "1,2"),
    ([1, "2", 3], "1,2,3"),
])
def test_puzzle_ids_accept_lists(session, puzzle_ids, expected):
    """Game state methods accept one ID, a comma separated string or a list."""
    session.get.return_value.json.return_value = {"user_id": 1, "states": []}
    NYTGamesClient(session=session).crossword_game(puzzle_ids)
    assert session.get.call_args.kwargs["params"] == {"puzzle_ids": expected}


def test_crossword_puzzles_rejects_midi(session):
    """NYT's list returns Daily puzzles for Midi, so the client refuses to ask."""
    with pytest.raises(ValueError, match="Midi"):
        NYTGamesClient(session=session).crossword_puzzles("midi")
    session.get.assert_not_called()


def test_archive_fetches_31_days_at_a_time(session):
    """The games archive allows 31 days per request, so longer ranges are split."""
    session.get.return_value.json.side_effect = [
        [{"id": 1, "print_date": "2026-01-01", "byline": "A"}],
        [{"id": 2, "print_date": "2026-02-01", "byline": "B"}],
        [{"id": 3, "print_date": "2026-03-04", "byline": "C"}],
    ]
    puzzles = NYTGamesClient(session=session).archive("crossword_midi", "2026-01-01", "2026-03-04")
    assert [p.id for p in puzzles] == [1, 2, 3]
    assert [c.args[0].rsplit("/svc/games/v1/archive/", 1)[1] for c in session.get.call_args_list] == [
        "crossword_midi/2026-01-01/2026-01-31",
        "crossword_midi/2026-02-01/2026-03-03",
        "crossword_midi/2026-03-04/2026-03-04",
    ]


def test_archive_keeps_game_specific_fields(session):
    session.get.return_value.json.return_value = [
        {"id": 1421, "print_date": "2026-10-04", "solution": "shack", "days_since_launch": 1933}]
    puzzle = NYTGamesClient(session=session).archive("wordle", "2026-10-04", "2026-10-04")[0]
    assert puzzle.model_dump()["solution"] == "shack"


def test_archive_rejects_unknown_games(session):
    with pytest.raises(ValueError):
        NYTGamesClient(session=session).archive("spelling_bee", "2026-10-04", "2026-10-04")
    session.get.assert_not_called()


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


def test_crossword_puzzles_null_results_are_empty(session):
    """NYT returns null results for empty or too long ranges."""
    session.get.return_value.json.return_value = {"status": "OK", "results": None}
    assert NYTGamesClient(session=session).crossword_puzzles("daily", date_start="2030-01-01").results == []


def test_archive_splits_windows_that_hit_the_limit(session):
    """A window with 31 puzzles may be cut short, so it's split and fetched again."""
    def day(n):
        return f"2022-12-{n:02d}"

    def response(path):
        start, end = path.rsplit("/", 2)[-2:]
        first, last = int(start[-2:]), int(end[-2:])
        puzzles = [{"id": 100 + n, "print_date": day(n)} for n in range(first, last + 1)]
        if first <= 31 <= last:
            puzzles.append({"id": 999, "print_date": day(31)})  # a second puzzle on the 31st
        return puzzles[-31:]  # NYT returns at most 31, dropping the earliest

    session.get.side_effect = lambda url, **kwargs: mock.Mock(
        status_code=200, json=mock.Mock(return_value=response(url)), raise_for_status=mock.Mock())
    puzzles = NYTGamesClient(session=session).archive("crossword_daily", "2022-12-01", "2022-12-31")
    assert len(puzzles) == 32
    assert puzzles[0].print_date == "2022-12-01"
    assert [p.id for p in puzzles if p.print_date == "2022-12-31"] == [131, 999]


def test_crossword_by_id(session):
    session.get.return_value.json.return_value = {
        "id": 20759, "body": [], "constructors": [], "copyright": "", "lastUpdated": "", "publicationDate": ""}
    assert NYTGamesClient(session=session).crossword_by_id(20759).id == 20759
    assert session.get.call_args.args[0] == "https://www.nytimes.com/svc/crosswords/v6/puzzle/20759.json"


@pytest.mark.parametrize("cookies", [
    json.dumps([{"domain": ".nytimes.com", "name": "NYT-S", "value": "abc="}, {"name": "nyt-a", "value": "def"}],
               indent=2),
    '{"NYT-S": "abc=", "nyt-a": "def"}',
])
def test_parse_cookies_json_strings(cookies):
    """A Cookie-Editor JSON export or a JSON object works as a string too."""
    assert parse_cookies(cookies) == {"NYT-S": "abc=", "nyt-a": "def"}


@pytest.mark.parametrize("cookies", [
    {"NYT-S": "SECRET\\nVALUE"},
    {"NYT-S": "SECRET;VALUE"},
    {"bad name": "SECRETVALUE"},
    '[{"name": "NYT-S", "value": "SECRETVALUE"',
])
def test_bad_cookies_never_show_their_values(cookies):
    """Cookies that can't be sent raise ValueError without the value in the message."""
    if isinstance(cookies, dict):
        cookies = {k: v.replace("\\n", "\n") for k, v in cookies.items()}
    with pytest.raises(ValueError) as info:
        NYTGamesClient(cookies=cookies)
    assert "SECRET" not in str(info.value)


def test_older_game_state_shapes(session):
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


@pytest.mark.parametrize("response", [
    {"user_id": 1, "states": [], "badges_trophy_shelf": {}},
    {"user_id": 1, "states": [], "player": None},
])
def test_player_stats_without_games_profile(session, response):
    """Accounts that have never played have no player; that's a clear error, still a KeyError."""
    session.get.return_value.json.return_value = response
    client = NYTGamesClient(cookies="NYT-S=abc", session=session)
    with pytest.raises(NYTGamesNoProfileError, match="no NYT Games profile"):
        client.player_stats()
    with pytest.raises(KeyError):
        client.player_stats()


def test_spelling_bee_latest_without_player(session):
    session.get.return_value.json.return_value = {"user_id": 1, "states": []}
    assert NYTGamesClient(session=session).spelling_bee_latest().player is None


def test_bonus_week_unexpected_response(session):
    session.get.return_value.json.return_value = {"error": "nope"}
    with pytest.raises(NYTGamesParseError):
        NYTGamesClient(session=session).bonus_week("2026-10-07")

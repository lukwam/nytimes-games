"""Bonus Puzzles tests, with NYT mocked.

Puzzles are real NYT responses from tests/fixtures/bonus; saved games are made up.
"""
import datetime
import json
import re
from unittest import mock as unittest_mock

import httpx
import pytest
from typer.testing import CliRunner

from nytgames import NYTGamesNotFoundError
from nytgames import NYTGamesParseError
from nytgames import views
from nytgames.cli import app as cli_main
from nytgames.cli import dates
from nytgames.cli.state import State
from nytgames.models import BonusWeek
from nytgames.models import ConnectionsLatest
from nytgames.models import ConnectionsPuzzle
from nytgames.models import CrosswordGame
from nytgames.models import StrandsLatest
from nytgames.models import StrandsPuzzle
from nytgames.models import WordleInOneLatest
from nytgames.models import WordleInOnePuzzle
from tests.support import COOKIES
from tests.support import NYT
from tests.support import USER_ID
from tests.support import load

WEEK_RESPONSE = load("bonus/week_2026-10-07.json")
WEEK = WEEK_RESPONSE["bonus_puzzles_week"]
WORDLE_IN_ONE = load("bonus/wordle_in_one_2026-10-07-8.json")
CONNECTIONS_3X3 = load("bonus/connections_2026-10-07-1270.json")
STRANDS = load("bonus/strands_2026-10-07-1130.json")
WEEK_URL = re.compile(re.escape(f"{NYT}/svc/games/bonus/week/v1/") + r"(?P<date>[\d-]+)\.json")


async def test_bonus_endpoints(api, mock):
    """Bonus puzzles are fetched by slug, and crosswords by ID."""
    mock.get(f"{NYT}/svc/games/bonus/week/v1/2026-10-07.json").respond(json=WEEK_RESPONSE)
    wordle = mock.get(f"{NYT}/svc/wordle-in-one/v1/bonus/2026-10-07-8.json").respond(json=WORDLE_IN_ONE)
    connections = mock.get(f"{NYT}/svc/connections/v2/bonus/2026-10-07-1270.json").respond(json=CONNECTIONS_3X3)
    strands = mock.get(f"{NYT}/svc/strands/v2/bonus/2026-10-07-1130.json").respond(json=STRANDS)
    crossword = mock.get(f"{NYT}/svc/crosswords/v6/puzzle/24411.json").respond(404)

    week = await api("bonus_week", "2026-10-07")
    assert week.drop_date == "2026-10-07" and week.next_drop == "2026-10-14"
    assert [p.slug for p in week.puzzles][:3] == ["2026-10-07-8", "2026-10-07-1270", "2026-10-07-1130"]
    assert [p.id for p in week.puzzles][3:] == [24411, 24127]

    puzzle = await api("bonus_puzzle", week.puzzles[0])
    assert isinstance(puzzle, WordleInOnePuzzle) and puzzle.rounds[0].start == "corgi"
    puzzle = await api("bonus_puzzle", week.puzzles[1])
    assert isinstance(puzzle, ConnectionsPuzzle) and puzzle.id == 1270
    puzzle = await api("bonus_puzzle", week.puzzles[2])
    assert isinstance(puzzle, StrandsPuzzle) and puzzle.spangram == "FINGERPAINTING"
    with pytest.raises(NYTGamesNotFoundError):
        await api("bonus_puzzle", week.puzzles[3])
    assert [r.call_count for r in (wordle, connections, strands, crossword)] == [1, 1, 1, 1]
    assert [call.request.url.path for call in mock.calls] == [
        "/svc/games/bonus/week/v1/2026-10-07.json", "/svc/wordle-in-one/v1/bonus/2026-10-07-8.json",
        "/svc/connections/v2/bonus/2026-10-07-1270.json", "/svc/strands/v2/bonus/2026-10-07-1130.json",
        "/svc/crosswords/v6/puzzle/24411.json"]


async def test_bonus_week_without_a_week_is_a_parse_error(api, mock):
    mock.get(f"{NYT}/svc/games/bonus/week/v1/2026-10-07.json").respond(json={"bonus_puzzles_week": None})
    with pytest.raises(NYTGamesParseError):
        await api("bonus_week", "2026-10-07")


@pytest.mark.parametrize("method,kwargs,game", [
    ("wordle_in_one_latest", {}, "wordle_in_one"),
    ("connections_latest", {"bonus": True}, "connections_bonus"),
    ("strands_latest", {"bonus": True}, "strands_bonus"),
    ("connections_latest", {}, "connections"),
])
async def test_bonus_game_states(logged_in, mock, method, kwargs, game):
    route = mock.get(f"{NYT}/svc/games/state/{game}/latests").respond(
        json={"user_id": USER_ID, "states": [], "badges_trophy_shelf": {}})
    result = await logged_in(method, [8, 7], **kwargs)
    assert result.user_id == USER_ID and result.states == []
    assert route.call_count == 1
    request = route.calls.last.request
    assert dict(request.url.params) == {"puzzle_ids": "8,7"}
    assert request.headers["Cookie"] == f"NYT-S={COOKIES['NYT-S']}"


def week_server(weeks: dict[str, dict]):
    """Answer bonus week requests from weeks keyed by the requested date; 404 for the rest."""
    def respond(request: httpx.Request, date: str) -> httpx.Response:
        if date not in weeks:
            return httpx.Response(404)
        return httpx.Response(200, json={"bonus_puzzles_week": weeks[date]})
    return respond


async def test_bonus_weeks_stop_at_unpublished_and_first_weeks(api, mock):
    """bonus_weeks follows next_drop, and stops at a 404 or the end date."""
    route = mock.get(WEEK_URL).mock(side_effect=week_server({
        "2026-08-20": {**WEEK, "drop_date": "2026-08-26", "prev_drop": "2026-08-19", "next_drop": "2026-09-02"},
        "2026-09-02": {**WEEK, "drop_date": "2026-09-02", "next_drop": "2026-09-09"},
    }))

    weeks = await api("bonus_weeks", "2026-08-20", "2026-12-31")
    assert [w.drop_date for w in weeks] == ["2026-08-26", "2026-09-02"]
    assert [call.request.url.path.rsplit("/", 1)[1] for call in route.calls] == [
        "2026-08-20.json", "2026-09-02.json", "2026-09-09.json"]
    assert route.calls.last.response.status_code == 404

    route.reset()
    weeks = await api("bonus_weeks", "2026-08-20", "2026-08-31")
    assert [w.drop_date for w in weeks] == ["2026-08-26"]
    assert route.call_count == 1


async def test_bonus_weeks_stop_at_weeks_that_go_backwards(api, mock):
    """A week whose next_drop points back at itself, or a next week that isn't newer, ends the list."""
    route = mock.get(WEEK_URL).mock(side_effect=week_server({
        "2026-10-07": {**WEEK, "next_drop": "2026-10-07"},
        "2026-09-23": {**WEEK, "drop_date": "2026-09-23", "next_drop": "2026-09-30"},
        "2026-09-30": {**WEEK, "drop_date": "2026-09-23", "next_drop": "2026-10-07"},
    }))
    assert [w.drop_date for w in await api("bonus_weeks", "2026-10-07", "2026-12-31")] == ["2026-10-07"]
    assert route.call_count == 1

    route.reset()
    assert [w.drop_date for w in await api("bonus_weeks", "2026-09-23", "2026-12-31")] == ["2026-09-23"]
    assert route.call_count == 2


def test_connections_3x3_board():
    puzzle = ConnectionsPuzzle(**CONNECTIONS_3X3)
    board = [["WE'D", "LOVE", "THAT"], ["DEUCE", "BREYER", "WHETHER"], ["FOR", "ADVANTAGE", "BUSCH"]]
    assert [[c.text for c in row] for row in puzzle.board()] == board
    assert views.connections_view(puzzle)["board"][0] == board[0]


def test_wordle_in_one_hides_solutions():
    puzzle = WordleInOnePuzzle(**WORDLE_IN_ONE)
    assert views.wordle_in_one_view(puzzle)["rounds"][:2] == [{"start": "corgi"}, {"start": "tiger"}]
    assert views.wordle_in_one_view(puzzle, answers=True)["rounds"][0] == {"start": "corgi", "solution": "grace"}


def test_find_bonus_listing():
    week = BonusWeek(**WEEK)
    assert views.find_bonus_listing(week, "special").id == 24127
    assert views.find_bonus_listing(week, "mini").id == 24411
    assert views.find_bonus_listing(week, "easy") is None


def state(game, puzzle_id, game_data):
    return {"game": game, "puzzle_id": str(puzzle_id), "game_data": game_data, "user_id": 1}


def test_bonus_results():
    client = unittest_mock.Mock()
    client.bonus_weeks.return_value = [BonusWeek(**WEEK)]
    client.wordle_in_one_latest.return_value = WordleInOneLatest(user_id=1, states=[state("wordle_in_one", 8, {
        "puzzleComplete": True, "currentRoundIndex": 4,
        "rounds": [{"complete": True, "timeMs": 4000}, {"complete": True, "timeMs": 6000}]})])
    client.connections_latest.return_value = ConnectionsLatest(user_id=1, states=[state(
        "connections_bonus", 1270, {"mistakes": 1, "puzzleComplete": True, "puzzleWon": True})])
    client.strands_latest.return_value = StrandsLatest(user_id=1, states=[])
    client.crossword_game.return_value = CrosswordGame(user_id=1, states=[state(
        "crossword_bonus", 24411, {"cells": {}, "firstSolve": 1, "playTimeSeconds": 95})])

    rows = views.bonus_results(client, datetime.date(2026, 10, 1), datetime.date(2026, 10, 7))

    assert [(r["title"], r["status"], r["detail"]) for r in rows] == [
        ("Wordle in 1", "solved", "2/2 rounds"), ("Connections 3x3", "won", "1 mistakes"),
        ("Colorful Strands", "not played", ""), ("Mystery Mini", "solved", "1:35"),
        ("Special Crossword", "not played", "")]
    client.connections_latest.assert_called_once_with([1270], bonus=True)
    client.crossword_game.assert_called_once_with([24411, 24127], "bonus")
    assert WordleInOneLatest(**client.wordle_in_one_latest.return_value.model_dump()).states[0].game_data.seconds == 10


@pytest.fixture
def cli_client(monkeypatch, tmp_path):
    monkeypatch.setenv("NYTG_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("NYT_COOKIES", raising=False)
    monkeypatch.setattr(dates, "today", lambda: datetime.date(2026, 10, 7))
    fake = unittest_mock.Mock()
    fake.bonus_week.return_value = BonusWeek(**WEEK)
    monkeypatch.setattr(State, "client", lambda self: fake)
    return fake


def run(*args):
    return CliRunner().invoke(cli_main.app, list(args))


def test_cli_bonus(cli_client):
    assert "Special Crossword" in run("bonus", "week").stdout
    assert json.loads(run("bonus", "week", "-f", "json").stdout)["puzzles"][1]["slug"] == "2026-10-07-1270"

    cli_client.bonus_puzzle.return_value = WordleInOnePuzzle(**WORDLE_IN_ONE)
    hidden = run("bonus", "wordle-in-one", "-f", "json").stdout
    assert "corgi" in hidden and "grace" not in hidden
    assert "grace" in run("bonus", "wordle-in-one", "--answers", "-f", "json").stdout

    cli_client.bonus_puzzle.return_value = ConnectionsPuzzle(**CONNECTIONS_3X3)
    assert "Connections 3x3" in run("bonus", "connections").stdout

    result = run("bonus", "crossword", "easy")
    assert result.exit_code == 1 and "No easy crossword puzzle" in result.stderr

"""Bonus Puzzles tests, with NYT mocked and made-up puzzles."""
import datetime
import json
from unittest import mock

import pytest
import requests
from typer.testing import CliRunner

from nytgames import NYTGamesClient
from nytgames import NYTGamesNotFoundError
from nytgames import views
from nytgames.cli import app as cli_main
from nytgames.cli import dates
from nytgames.cli.state import State
from nytgames.models import BonusWeek
from nytgames.models import ConnectionsLatest
from nytgames.models import ConnectionsPuzzle
from nytgames.models import CrosswordGame
from nytgames.models import StrandsLatest
from nytgames.models import WordleInOneLatest
from nytgames.models import WordleInOnePuzzle


def listing(game, variant, puzzle_id, title):
    return {"game": game, "variant": variant, "title": title, "subtitle": "Sub", "editors": ["Ed"],
            "constructors": "", "card_byline": "By ED", "make_free": False, "id": puzzle_id,
            "slug": f"2026-10-07-{puzzle_id}", "web_url": "/games/bonus/x", "additional_data": {}}


WEEK = {"display_free": False, "drop_date": "2026-10-07", "prev_drop": "2026-09-30", "next_drop": "2026-10-14",
        "week_in_month": 1, "puzzles": [
            listing("wordle-in-one", "standard", 8, "Wordle in 1"),
            listing("connections", "3x3", 1270, "Connections 3x3"),
            listing("strands", "colorful", 1130, "Colorful Strands"),
            listing("crossword", "mini", 24411, "Mystery Mini"),
            listing("crossword", "monthly", 24127, "Special Crossword"),
        ]}

WORDLE_IN_ONE = {"status": "OK", "id": 8, "slug": "2026-10-07-8", "title": "Wordle in 1",
                 "print_date": "2026-10-07", "editor": "Ed", "stream": "bonus", "make_free": False,
                 "rounds": [{"start": "aaaaa", "solution": "bbbbb"}, {"start": "ccccc", "solution": "ddddd"}]}

CONNECTIONS_3X3 = {"status": "OK", "id": 1270, "title": "Connections 3x3", "print_date": "2026-10-07",
                   "editor": "Ed", "stream": "bonus", "tags": ["variant:3x3"], "categories": [
                       {"title": f"GROUP {g}", "cards": [{"content": f"W{g}{i}", "position": i * 3 + g}
                                                        for i in range(3)]} for g in range(3)]}


@pytest.fixture
def session():
    session = mock.Mock(spec=requests.Session)
    session.get.return_value.status_code = 200
    return session


def test_bonus_endpoints(session):
    """Bonus puzzles are fetched by slug, and crosswords by ID."""
    client = NYTGamesClient(session=session)
    session.get.return_value.json.return_value = {"bonus_puzzles_week": WEEK}
    week = client.bonus_week("2026-10-07")
    assert session.get.call_args.args[0] == "https://www.nytimes.com/svc/games/bonus/week/v1/2026-10-07.json"
    assert [p.slug for p in week.puzzles][:2] == ["2026-10-07-8", "2026-10-07-1270"]

    for item, path in ((week.puzzles[0], "/svc/wordle-in-one/v1/bonus/2026-10-07-8.json"),
                       (week.puzzles[1], "/svc/connections/v2/bonus/2026-10-07-1270.json")):
        session.get.return_value.json.return_value = WORDLE_IN_ONE if item.game == "wordle-in-one" else CONNECTIONS_3X3
        client.bonus_puzzle(item)
        assert session.get.call_args.args[0] == "https://www.nytimes.com" + path
    paths = []

    def get(path, params=None, json_response=True):
        paths.append(path)
        raise NYTGamesNotFoundError("404")

    with mock.patch.object(client, "_get", side_effect=get):
        for item in week.puzzles[2:4]:
            with pytest.raises(NYTGamesNotFoundError):
                client.bonus_puzzle(item)
    assert paths == ["/svc/strands/v2/bonus/2026-10-07-1130.json", "/svc/crosswords/v6/puzzle/24411.json"]


@pytest.mark.parametrize("method,kwargs,game", [
    ("wordle_in_one_latest", {}, "wordle_in_one"),
    ("connections_latest", {"bonus": True}, "connections_bonus"),
    ("strands_latest", {"bonus": True}, "strands_bonus"),
    ("connections_latest", {}, "connections"),
])
def test_bonus_game_states(session, method, kwargs, game):
    session.get.return_value.json.return_value = {"user_id": 1, "states": [], "badges_trophy_shelf": {}}
    getattr(NYTGamesClient(session=session), method)([8, 7], **kwargs)
    assert session.get.call_args.args[0] == f"https://www.nytimes.com/svc/games/state/{game}/latests"
    assert session.get.call_args.kwargs["params"] == {"puzzle_ids": "8,7"}


def test_bonus_weeks_stop_at_unpublished_and_first_weeks():
    """bonus_weeks follows next_drop, and stops at a 404 or a week pointing back at itself."""
    client = NYTGamesClient()
    weeks = {
        "2026-08-20": {**WEEK, "drop_date": "2026-08-26", "prev_drop": "2026-08-19", "next_drop": "2026-09-02"},
        "2026-09-02": {**WEEK, "drop_date": "2026-09-02", "next_drop": "2026-09-09"},
    }

    def get(path, params=None, json_response=True):
        date = path.rsplit("/", 1)[1].removesuffix(".json")
        if date not in weeks:
            raise NYTGamesNotFoundError("404")
        return {"bonus_puzzles_week": weeks[date]}

    with mock.patch.object(client, "_get", side_effect=get):
        assert [w.drop_date for w in client.bonus_weeks("2026-08-20", "2026-12-31")] == ["2026-08-26", "2026-09-02"]
        assert [w.drop_date for w in client.bonus_weeks("2026-08-20", "2026-08-31")] == ["2026-08-26"]


def test_connections_3x3_board():
    puzzle = ConnectionsPuzzle(**CONNECTIONS_3X3)
    assert [[c.text for c in row] for row in puzzle.board()] == [
        ["W00", "W10", "W20"], ["W01", "W11", "W21"], ["W02", "W12", "W22"]]
    assert views.connections_view(puzzle)["board"][0] == ["W00", "W10", "W20"]


def test_wordle_in_one_hides_solutions():
    puzzle = WordleInOnePuzzle(**WORDLE_IN_ONE)
    assert views.wordle_in_one_view(puzzle)["rounds"] == [{"start": "aaaaa"}, {"start": "ccccc"}]
    assert views.wordle_in_one_view(puzzle, answers=True)["rounds"][0] == {"start": "aaaaa", "solution": "bbbbb"}


def test_find_bonus_listing():
    week = BonusWeek(**WEEK)
    assert views.find_bonus_listing(week, "special").id == 24127
    assert views.find_bonus_listing(week, "mini").id == 24411
    assert views.find_bonus_listing(week, "easy") is None


def state(game, puzzle_id, game_data):
    return {"game": game, "puzzle_id": str(puzzle_id), "game_data": game_data, "user_id": 1}


def test_bonus_results():
    client = mock.Mock()
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
    fake = mock.Mock()
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
    assert "aaaaa" in hidden and "bbbbb" not in hidden
    assert "bbbbb" in run("bonus", "wordle-in-one", "--answers", "-f", "json").stdout

    cli_client.bonus_puzzle.return_value = ConnectionsPuzzle(**CONNECTIONS_3X3)
    assert "Connections 3x3" in run("bonus", "connections").stdout

    result = run("bonus", "crossword", "easy")
    assert result.exit_code == 1 and "No easy crossword puzzle" in result.stderr

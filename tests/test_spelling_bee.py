"""Spelling Bee puzzles and hints tests.

The hints cases are ported from nyt-puzzles so both stay in agreement. The
game page and the dated puzzle are real NYT responses from tests/fixtures.
"""
import json

import pytest
from fastapi.testclient import TestClient

from nytgames import NYTGamesNotFoundError
from nytgames import NYTGamesParseError
from nytgames import api as main
from nytgames import spelling_bee_hints
from nytgames.models import SpellingBeeGameDay
from nytgames.models import SpellingBeePuzzle
from tests.support import NYT
from tests.support import USER_ID
from tests.support import load
from tests.support import text

PAGE_URL = f"{NYT}/puzzles/spelling-bee"
PAGE = text("spelling_bee/page.html")
PUZZLE_URL = f"{NYT}/svc/spelling-bee/v1/2025-06-12.json"
PUZZLE = load("spelling_bee/2025-06-12.json")


def make_puzzle(print_date, answers, letters="iabchln", pangrams=None):
    """Build a puzzle shaped like the ones on the public Spelling Bee page."""
    return {
        "answers": answers,
        "centerLetter": letters[0],
        "displayDate": print_date,
        "displayWeekday": "Saturday",
        "editor": "Sam Ezersky",
        "freeExpiration": 0,
        "id": 1,
        "outerLetters": list(letters[1:]),
        "pangrams": pangrams or [],
        "printDate": print_date,
        "validLetters": list(letters),
    }


def test_hints_counts_words_by_first_letter_and_length():
    puzzle = make_puzzle("2026-10-03", ["chin", "hail", "laicb", "bacchanalia"])

    hints = spelling_bee_hints(puzzle)

    assert hints["counts"] == {
        "lengths": [4, 5, 11],
        "letters": {"b": [0, 0, 1, 1], "c": [1, 0, 0, 1], "h": [1, 0, 0, 1], "l": [0, 1, 0, 1]},
        "totals": [2, 1, 1, 4],
    }
    assert hints["pairs"] == {"ba": 1, "ch": 1, "ha": 1, "la": 1}
    assert hints["letters"] == ["i", "a", "b", "c", "h", "l", "n"]
    assert hints["date"] == "2026-10-03"
    assert hints["words"] == 4


def test_hints_score_pangrams_with_bonus():
    # 4-letter words score 1; longer words score their length, plus 7 for a pangram.
    puzzle = make_puzzle("2026-10-03", ["chin", "hail", "bacchanalia"])

    hints = spelling_bee_hints(puzzle)

    assert hints["pangrams"] == 1
    assert hints["points"] == 1 + 1 + 11 + 7
    assert "perfect" not in hints


def test_hints_count_perfect_pangrams():
    puzzle = make_puzzle("2026-10-03", ["blanchi", "chin"])

    assert spelling_bee_hints(puzzle)["perfect"] == 1


def test_hints_mark_bingo_only_when_every_letter_starts_a_word():
    answers = ["inch", "abba", "bail", "chai", "hail", "lain", "nail"]

    assert spelling_bee_hints(make_puzzle("d", answers))["bingo"] is True
    assert "bingo" not in spelling_bee_hints(make_puzzle("d", answers[1:]))


def test_hints_lowercase_answers():
    hints = spelling_bee_hints(make_puzzle("d", ["CHIN"]))

    assert hints["pairs"] == {"ch": 1}


def test_hints_accept_a_model():
    puzzle = make_puzzle("2026-10-03", ["chin", "hail", "bacchanalia"])

    assert spelling_bee_hints(SpellingBeeGameDay(**puzzle)) == spelling_bee_hints(puzzle)


async def test_spelling_bee_puzzles_reads_every_puzzle_on_the_page(api, mock):
    route = mock.get(PAGE_URL).respond(text=PAGE)
    puzzles = await api("spelling_bee_puzzles")

    assert route.call_count == 1
    assert list(puzzles) == [f"2026-10-{day:02}" for day in range(5, 13)]
    game_data = json.loads(PAGE.split("window.gameData = ", 1)[1].split("</script>", 1)[0])
    assert puzzles["2026-10-12"].answers == game_data["today"]["answers"]
    assert puzzles["2026-10-12"].pangrams == ["empathy"] and puzzles["2026-10-12"].centerLetter == "e"
    assert puzzles["2026-10-05"].answers == game_data["pastPuzzles"]["lastWeek"][0]["answers"]


async def test_spelling_bee_fails_without_game_data(api, mock):
    mock.get(PAGE_URL).respond(text="<html></html>")

    with pytest.raises(ValueError, match="game data not found") as error:
        await api("spelling_bee_puzzles")
    assert isinstance(error.value, NYTGamesParseError)


V1_PUZZLE = {
    "id": 24710,
    "answers": ["chin", "hail"],
    "center_letter": "i",
    "editor": "Sam Ezersky",
    "outer_letters": "abchln",
    "pangrams": ["bacchanalia"],
    "print_date": "2026-10-03",
}


def test_v1_puzzle_converts_to_the_game_page_format():
    day = SpellingBeePuzzle(**V1_PUZZLE).to_game_day()

    # v1 answers leave out the pangrams; the game page lists them first.
    assert day.answers == ["bacchanalia", "chin", "hail"]
    assert day.pangrams == ["bacchanalia"]
    assert day.centerLetter == "i"
    assert day.outerLetters == ["a", "b", "c", "h", "l", "n"]
    assert day.validLetters == ["i", "a", "b", "c", "h", "l", "n"]
    assert day.displayDate == "October 3, 2026"
    assert day.displayWeekday == "Saturday"
    assert day.printDate == "2026-10-03"
    assert day.id == 24710
    assert day.freeExpiration is None


def test_v1_puzzle_matches_page_puzzle_hints():
    page_day = make_puzzle("2026-10-03", ["bacchanalia", "chin", "hail"], pangrams=["bacchanalia"])

    v1_day = SpellingBeePuzzle(**V1_PUZZLE).to_game_day()

    assert spelling_bee_hints(v1_day) == spelling_bee_hints(page_day)


async def test_spelling_bee_puzzle_by_date(api, mock):
    route = mock.get(PUZZLE_URL).respond(json=PUZZLE)
    day = await api("spelling_bee_puzzle", "2025-06-12")

    assert route.call_count == 1
    assert day.answers[:5] == ["clodding", "coddling", "colliding", "condoling", "clod"]
    assert day.answers == PUZZLE["pangrams"] + PUZZLE["answers"]
    assert day.centerLetter == "d" and day.printDate == "2025-06-12"
    assert day.displayDate == "June 12, 2025" and day.displayWeekday == "Thursday"


async def test_spelling_bee_puzzle_missing_date_raises_not_found(api, mock):
    route = mock.get(f"{NYT}/svc/spelling-bee/v1/2018-05-01.json").respond(404)

    with pytest.raises(NYTGamesNotFoundError):
        await api("spelling_bee_puzzle", "2018-05-01")
    assert route.call_count == 1


def test_api_date_route(mock):
    mock.get(PUZZLE_URL).respond(json=PUZZLE)
    response = TestClient(main.app).get("/spelling-bee/2025-06-12")

    assert response.status_code == 200
    assert response.json()["answers"] == PUZZLE["pangrams"] + PUZZLE["answers"]


def test_api_date_route_returns_404_for_missing_dates(mock):
    mock.get(f"{NYT}/svc/spelling-bee/v1/2018-05-01.json").respond(404)

    assert TestClient(main.app).get("/spelling-bee/2018-05-01").status_code == 404


def test_api_hints_route(mock):
    mock.get(PUZZLE_URL).respond(json=PUZZLE)
    response = TestClient(main.app).get("/spelling-bee/2025-06-12/hints")

    assert response.status_code == 200
    assert response.json() == spelling_bee_hints(SpellingBeePuzzle(**PUZZLE).to_game_day())
    assert response.json()["pangrams"] == 4


def test_api_latest_route_is_not_treated_as_a_date(mock):
    route = mock.get(f"{NYT}/svc/games/state/spelling_bee/latests").respond(
        json={"user_id": USER_ID, "states": []})

    response = TestClient(main.app).get("/spelling-bee/latest")

    assert route.call_count == 1 and len(mock.calls) == 1
    assert response.status_code == 200 and response.json()["user_id"] == USER_ID

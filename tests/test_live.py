"""Live checks against NYT.

Deselected by default; run with `pytest -m live`. Each test makes one or two
requests, to notice when NYT changes how it answers.
"""
import pytest

from nytgames import NYTGamesAuthenticationError
from nytgames import NYTGamesClient
from nytgames import NYTGamesNotFoundError

pytestmark = pytest.mark.live

DATE = "2025-06-12"


@pytest.fixture(scope="module")
def client():
    return NYTGamesClient()


def test_wordle(client):
    puzzle = client.wordle(DATE)
    assert puzzle.solution == "vixen" and puzzle.days_since_launch == 1454


def test_wordle_future_date(client):
    with pytest.raises(NYTGamesNotFoundError):
        client.wordle("2099-01-01")


def test_connections(client):
    puzzle = client.connections(DATE)
    assert puzzle.id == 765 and len(puzzle.categories) == 4
    assert puzzle.categories[0].title == "GETTING COZY"


def test_strands(client):
    puzzle = client.strands(DATE)
    assert puzzle.spangram == "TACKLEBOX" and len(puzzle.themeWords) == 8


def test_spelling_bee(client):
    puzzle = client.spelling_bee_puzzle(DATE)
    assert puzzle.centerLetter == "d" and "coddling" in puzzle.pangrams


def test_letter_boxed(client):
    puzzle = client.letter_boxed(DATE)
    assert puzzle.sides == ["ZAI", "BRL", "DUE", "TOV"] and puzzle.par == 6


def test_crossword(client):
    puzzle = client.crossword("daily", DATE)
    assert puzzle.id == 22852
    assert next(e for e in puzzle.entries() if e.id == "50-Across").answer == "QUADRUPLEDOUBLE"


def test_unknown_crossword(client):
    with pytest.raises(NYTGamesNotFoundError):
        client.crossword_by_id(99999999)


def test_archive(client):
    puzzles = client.archive("wordle", "2025-06-10", DATE)
    assert [p.print_date for p in puzzles] == ["2025-06-10", "2025-06-11", DATE]


def test_wordlebot_summary(client):
    assert client.wordlebot_summary(DATE).average["normal"] > 3


def test_bonus_week(client):
    assert client.bonus_week("2026-10-07").puzzles[0].slug == "2026-10-07-8"


def test_stats_with_a_fake_login():
    """NYT answers a cookie it doesn't accept with 403."""
    with pytest.raises(NYTGamesAuthenticationError):
        NYTGamesClient(cookies={"NYT-S": "0^not-a-real-cookie"}).player_stats()

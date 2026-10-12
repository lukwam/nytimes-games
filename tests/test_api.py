"""NYT Games API tests.

These tests serve the API with FastAPI's TestClient and mock the upstream
NYT requests with respx, so they run offline and do not need NYT cookies.
"""
import httpx
import pytest
from fastapi import FastAPI
from fastapi import Request
from fastapi.testclient import TestClient

from nytgames import NYTGamesClient
from nytgames import api as main
from nytgames.client import get_game_data
from tests.support import COOKIES
from tests.support import NYT
from tests.support import load
from tests.support import text

client = TestClient(main.app)

#: Wordle's first puzzle, which predates days_since_launch and editor.
WORDLE_FIRST = {
    "id": 1,
    "solution": "cigar",
    "print_date": "2021-06-19",
}

CROSSWORD_DAILY = {
    "id": 1,
    "constructors": ["A. Constructor"],
    "copyright": "2025",
    "editor": "Will Shortz",
    "lastUpdated": "2025-06-12 00:00:00 +0000 UTC",
    "publicationDate": "2025-06-12",
    "relatedContent": {"text": "", "url": ""},
    "body": [{
        "board": "<svg></svg>",
        "cells": [
            {"answer": "A", "clues": [0], "label": 1, "type": 1},
            {"answer": "LL", "clues": [0], "moreAnswers": {"valid": ["L"]}, "type": 1},
            {},
        ],
        "clues": [{
            "cells": [0, 1],
            "direction": "Across",
            "label": "1",
            "text": [{"plain": "Clue"}],
        }],
        "clueLists": [{"clues": [0], "name": "Across"}],
        "dimensions": {"height": 1, "width": 3},
        "SVG": {},
    }],
}

STATE_LATESTS = {
    "user_id": 123,
    "states": [],
    "player": {
        "user_id": 123,
        "last_updated": 0,
        "stats": {
            "spelling_bee": {
                "puzzles_started": 1,
                "total_words": 2,
                "total_pangrams": 0,
                "longest_word": {"word": "abcd", "center_letter": "a", "print_date": "2025-06-12"},
                "ranks": {
                    "Amazing": 0, "Beginner": 0, "Genius": 0, "Good": 0, "Good Start": 0,
                    "Great": 0, "Moving Up": 0, "Nice": 0, "Queen Bee": 0, "Solid": 0,
                },
            },
            "wordle": {"legacyStats": {
                "autoOptInTimestamp": 0, "currentStreak": 0, "gamesPlayed": 0, "gamesWon": 0,
                "guesses": {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0, "6": 0, "fail": 0},
                "hasMadeStatsChoice": False, "hasPlayed": False, "lastWonDayOffset": 0,
                "maxStreak": 0, "timestamp": 0,
            }},
        },
    },
    "badges_trophy_shelf": [],
    "crossword_archive_streaks": {"vertical": None, "horizontal": None},
}


def no_backoff_app() -> FastAPI:
    """The API with a client that retries without sleeping, using the request's cookies."""
    def get_client(request: Request) -> NYTGamesClient:
        return NYTGamesClient(cookies=request.cookies, backoff=0)

    app = main.create_app()
    app.dependency_overrides[main.get_client] = get_client
    return app


def test_wordle_early_puzzle_without_optional_fields(mock):
    """Early Wordle puzzles have no days_since_launch or editor."""
    route = mock.get(f"{NYT}/svc/wordle/v2/2021-06-19.json").respond(json=WORDLE_FIRST)
    response = client.get("/wordle/2021-06-19")
    assert response.status_code == 200
    assert response.json()["solution"] == "cigar"
    assert route.call_count == 1


def test_wordle(mock):
    """A real Wordle response is returned as is."""
    puzzle = load("wordle/2025-06-12.json")
    mock.get(f"{NYT}/svc/wordle/v2/2025-06-12.json").respond(json=puzzle)
    response = client.get("/wordle/2025-06-12")
    assert response.status_code == 200
    assert response.json() == puzzle


def test_unknown_fields_are_passed_through(mock):
    """New NYT fields do not break validation and appear in the response."""
    mock.get(f"{NYT}/svc/wordle/v2/2025-06-12.json").respond(
        json={**load("wordle/2025-06-12.json"), "new_field": "value"})
    response = client.get("/wordle/2025-06-12")
    assert response.status_code == 200
    assert response.json()["new_field"] == "value"


def test_crossword_daily_uses_v6_endpoint(mock):
    """Daily crosswords use the v6 format, including rebus cells."""
    route = mock.get(f"{NYT}/svc/crosswords/v6/puzzle/daily/2025-06-12.json").respond(json=CROSSWORD_DAILY)
    response = client.get("/crosswords/daily/2025-06-12")
    assert response.status_code == 200
    cell = response.json()["body"][0]["cells"][1]
    assert cell["answer"] == "LL"
    assert cell["moreAnswers"] == {"valid": ["L"]}
    assert route.call_count == 1


@pytest.mark.parametrize("path,game", [("/connections/latest", "connections"),
                                       ("/spelling-bee/latest", "spelling_bee"),
                                       ("/strands/latest", "strands"),
                                       ("/wordle/latest", "wordleV2")])
def test_state_latests(mock, path, game):
    """Game state endpoints accept the current response shape."""
    route = mock.get(f"{NYT}/svc/games/state/{game}/latests").respond(json=STATE_LATESTS)
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["user_id"] == 123
    assert route.call_count == 1


def test_strands_uses_v2_endpoint(mock):
    """Strands is fetched from the svc/strands/v2 endpoint."""
    puzzle = load("strands/2025-06-12.json")
    route = mock.get(f"{NYT}/svc/strands/v2/2025-06-12.json").respond(json=puzzle)
    response = client.get("/strands/2025-06-12")
    assert response.status_code == 200
    assert response.json()["spangram"] == puzzle["spangram"]
    assert route.call_count == 1


def test_upstream_error_status_is_passed_through(mock):
    """Upstream NYT errors return the upstream status code, not a 500."""
    mock.get(f"{NYT}/svc/wordle/v2/1900-01-01.json").respond(404)
    response = client.get("/wordle/1900-01-01")
    assert response.status_code == 404
    assert response.json()["detail"] == "NYT API returned 404"


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
def test_upstream_errors_are_mapped(mock, status):
    """Auth, not found, rate limit and server errors keep NYT's status code."""
    route = mock.get(f"{NYT}/svc/wordle/v2/2025-06-12.json").respond(status)
    response = TestClient(no_backoff_app()).get("/wordle/2025-06-12")
    assert response.status_code == status
    assert response.json() == {"detail": f"NYT API returned {status}"}
    # Rate limits and server errors are retried (3 times by default) first.
    assert route.call_count == (4 if status in (429, 500, 503) else 1)


def test_get_game_data():
    """Spelling Bee game data is parsed from the page script tag."""
    body = b'<html><script>window.gameData = {"today": {"id": 1}}</script></html>'
    assert get_game_data(body) == {"today": {"id": 1}}
    assert get_game_data(b"<html></html>") is None
    assert get_game_data(text("spelling_bee/page.html"))["today"]["printDate"] == "2026-10-12"


def test_spelling_bee_page(mock):
    """Spelling Bee game data is scraped from the real game page."""
    mock.get(f"{NYT}/puzzles/spelling-bee").respond(text=text("spelling_bee/page.html"))
    response = client.get("/spelling-bee")
    assert response.status_code == 200
    assert response.json()["today"]["centerLetter"] == "e"


def test_crossword_game_uses_game_state_endpoint(mock):
    """Crossword game state is fetched from the games state service."""
    route = mock.get(f"{NYT}/svc/games/state/crossword_mini/latests").respond(json={
        "user_id": 123,
        "player": {},
        "states": [{
            "game": "crossword_mini",
            "game_data": {"cells": {}, "playTimeSeconds": 30, "star": "blue"},
            "print_date": "2026-07-17",
            "puzzle_id": "24291",
            "timestamp": 0,
            "user_id": 123,
        }],
        "crossword_archive_streaks": {"vertical": None, "horizontal": None},
    })
    response = client.get("/crosswords/game/24291?publish_type=mini")
    assert response.status_code == 200
    assert response.json()["states"][0]["game_data"]["playTimeSeconds"] == 30
    assert route.call_count == 1
    assert dict(route.calls.last.request.url.params) == {"puzzle_ids": "24291"}


@pytest.mark.parametrize("publish_type", ["daily", "midi"])
def test_crossword_oracle(mock, publish_type):
    """The oracle returns the current and next puzzle."""
    oracle = load("crossword/oracle_daily.json")
    route = mock.get(f"{NYT}/svc/crosswords/v2/oracle/{publish_type}.json").respond(json=oracle)
    response = client.get(f"/crosswords/oracle/{publish_type}")
    assert response.status_code == 200
    assert response.json()["results"]["current"]["puzzle_id"] == oracle["results"]["current"]["puzzle_id"]
    assert response.json()["results"]["next"]["puzzle_id"] == oracle["results"]["next"]["puzzle_id"]
    assert route.call_count == 1


def test_crossword_oracle_rejects_unknown_type(mock):
    """Unknown publish types are rejected before calling NYT."""
    assert client.get("/crosswords/oracle/nope").status_code == 422
    assert not mock.calls


def test_wordle_latest_states_are_models(mock):
    """Wordle game states are validated like the other game states."""
    route = mock.get(f"{NYT}/svc/games/state/wordleV2/latests").respond(json={
        "user_id": 123,
        "player": {},
        "states": [{
            "game": "wordleV2",
            "game_data": {
                "boardState": ["crane", "", "", "", "", ""],
                "currentRowIndex": 1,
                "hardMode": True,
                "isPlayingArchive": False,
                "status": "IN_PROGRESS",
            },
            "print_date": "2026-09-30",
            "puzzle_id": "829",
            "schema_version": "0.52.0",
            "timestamp": 0,
            "user_id": 123,
            "version": "1",
        }],
    })
    response = client.get("/wordle/latest?puzzle_ids=829")
    assert response.status_code == 200
    assert response.json()["states"][0]["game_data"]["status"] == "IN_PROGRESS"
    assert dict(route.calls.last.request.url.params) == {"puzzle_ids": "829"}


def test_create_app_accepts_fastapi_settings():
    """create_app() passes settings through to FastAPI."""
    app = main.create_app(title="My NYT API", docs_url=None)
    assert app.title == "My NYT API"
    assert TestClient(app).get("/docs").status_code == 404


def test_cookies_are_forwarded_to_nyt(mock):
    """Cookies sent to the API are sent on to NYT."""
    route = mock.get(f"{NYT}/svc/games/state/wordleV2/latests").respond(json=STATE_LATESTS)
    response = TestClient(main.app, cookies=COOKIES).get("/player/stats")
    assert response.status_code == 200
    assert response.json()["user_id"] == 123
    assert route.calls.last.request.headers["Cookie"] == "; ".join(f"{k}={v}" for k, v in COOKIES.items())
    assert dict(route.calls.last.request.url.params) == {"puzzle_ids": "0"}


def test_no_cookies_are_sent_without_request_cookies(mock):
    """Without cookies on the API request, none are sent to NYT."""
    route = mock.get(f"{NYT}/svc/wordle/v2/2025-06-12.json").respond(json=load("wordle/2025-06-12.json"))
    assert client.get("/wordle/2025-06-12").status_code == 200
    assert "Cookie" not in route.calls.last.request.headers


def test_router_mounts_in_your_own_app_with_your_own_client(mock):
    """The router can be mounted under a prefix, with a client using your cookies."""
    app = FastAPI()
    app.include_router(main.router, prefix="/nyt")
    main.add_exception_handlers(app)
    app.dependency_overrides[main.get_client] = lambda: NYTGamesClient(cookies="NYT-S=server")

    route = mock.get(f"{NYT}/svc/wordle/v2/2025-06-12.json").respond(json=load("wordle/2025-06-12.json"))
    # The override's cookies are used, not the ones sent to the API.
    response = TestClient(app, cookies={"NYT-S": "browser"}).get("/nyt/wordle/2025-06-12")
    assert response.status_code == 200
    assert route.calls.last.request.headers["Cookie"] == "NYT-S=server"

    mock.get(f"{NYT}/svc/wordle/v2/1900-01-01.json").respond(404)
    assert TestClient(app).get("/nyt/wordle/1900-01-01").status_code == 404


def test_parse_errors_return_502(mock):
    """A Spelling Bee page without game data returns 502, not 500."""
    mock.get(f"{NYT}/puzzles/spelling-bee").respond(text="<html></html>")
    response = client.get("/spelling-bee")
    assert response.status_code == 502
    assert response.json()["detail"] == "Spelling Bee game data not found in the page"


def test_non_json_responses_return_502(mock):
    """An NYT JSON endpoint that returns something else is a 502, not a 500."""
    mock.get(f"{NYT}/svc/wordle/v2/2025-06-12.json").respond(text="<html>maintenance</html>")
    response = client.get("/wordle/2025-06-12")
    assert response.status_code == 502


def test_crossword_puzzles_midi_is_a_bad_request(mock):
    """NYT's list doesn't include Midi puzzles, so the API says so."""
    response = client.get("/crosswords/puzzles?publish_type=midi")
    assert response.status_code == 400
    assert not mock.calls


@pytest.mark.parametrize("game,game_data", [
    ("connections", {"guesses": [{"cards": []}], "mistakes": 1, "puzzleComplete": True, "puzzleWon": True,
                     "solvedCategories": [{"title": "A"}], "isPlayingArchive": False, "newField": 1}),
    ("strands", {"history": [{"word": "HOOK"}], "isSolved": True, "otherWordsFound": ["CAST"],
                 "isPlayingArchive": False, "newField": 1}),
    ("connections", {}),
    ("strands", {}),
])
def test_connections_and_strands_latest(mock, game, game_data):
    """Connections and Strands game states use the game state service and allow any game data."""
    route = mock.get(f"{NYT}/svc/games/state/{game}/latests").respond(json={
        **STATE_LATESTS,
        "badges_trophy_shelf": {},
        "crossword_archive_streaks": {},
        "states": [{"game": game, "game_data": game_data, "print_date": "", "puzzle_id": "1315",
                    "schema_version": "0.1.0", "timestamp": 0, "user_id": 123, "version": "1"}],
    })
    response = client.get(f"/{game}/latest?puzzle_ids=1315,1314")
    assert response.status_code == 200
    state = response.json()["states"][0]
    assert state["puzzle_id"] == "1315"
    assert state["game_data"].get("newField") == game_data.get("newField")
    assert route.call_count == 1
    assert dict(route.calls.last.request.url.params) == {"puzzle_ids": "1315,1314"}


def test_badges(mock):
    """Badges come from the trophy case, one request per game."""
    route = mock.get(url__regex=rf"^{NYT}/svc/games/badges/trophy-case/(?P<game>[^/?]+)$")
    route.side_effect = lambda request, game: httpx.Response(200, json={"user_id": 123, "trophies": {game: {
        "earned": [{"id": "cx7", "badge_type": "progress", "progress": 2, "earned_at": [1], "earned": True}],
        "unearned": []}}})
    response = client.get("/badges/connections")
    assert response.status_code == 200
    assert response.json()["trophies"]["connections"]["earned"][0]["id"] == "cx7"
    assert route.calls.last.request.url == f"{NYT}/svc/games/badges/trophy-case/connections"
    assert client.get("/badges/wordle").status_code == 422
    assert route.call_count == 1

    response = client.get("/badges")
    assert response.status_code == 200
    assert set(response.json()["trophies"]) == {"wordleV2", "connections", "strands", "spelling_bee"}
    assert route.call_count == 5


def test_bonus_routes(mock):
    """Bonus routes use the bonus week, puzzle and game state endpoints."""
    mock.get(f"{NYT}/svc/games/bonus/week/v1/2026-10-07.json").respond(json=load("bonus/week_2026-10-07.json"))
    response = client.get("/bonus/week/2026-10-07")
    assert response.status_code == 200
    assert response.json()["puzzles"][0]["slug"] == "2026-10-07-8"

    mock.get(f"{NYT}/svc/wordle-in-one/v1/bonus/2026-10-07-8.json").respond(
        json=load("bonus/wordle_in_one_2026-10-07-8.json"))
    response = client.get("/bonus/wordle-in-one/2026-10-07-8")
    assert response.status_code == 200
    assert response.json()["rounds"][0]["start"] == "corgi"

    for path, game in (("wordle-in-one", "wordle_in_one"), ("connections", "connections_bonus"),
                       ("strands", "strands_bonus")):
        route = mock.get(f"{NYT}/svc/games/state/{game}/latests").respond(json={**STATE_LATESTS, "states": []})
        assert client.get(f"/bonus/{path}/latest?puzzle_ids=8").status_code == 200
        assert route.call_count == 1
        assert dict(route.calls.last.request.url.params) == {"puzzle_ids": "8"}


def test_player_stats_without_games_profile(mock):
    """Accounts with no NYT Games profile get a 404 with a reason."""
    mock.get(f"{NYT}/svc/games/state/wordleV2/latests").respond(json={"user_id": 1, "states": []})
    response = client.get("/player/stats")
    assert response.status_code == 404
    assert "no NYT Games profile" in response.json()["detail"]


def test_openapi_lists_every_route_under_a_tag():
    schema = client.get("/openapi.json").json()
    tags = {tag["name"] for tag in schema["tags"]}
    for path, methods in schema["paths"].items():
        assert set(methods) == {"get"}, path  # read-only
        assert set(methods["get"]["tags"]) <= tags, path


def test_each_request_closes_its_client(mock, monkeypatch):
    mock.get(f"{NYT}/svc/wordle/v2/2025-06-12.json").respond(json=load("wordle/2025-06-12.json"))
    closed = []
    monkeypatch.setattr(NYTGamesClient, "close", lambda self: closed.append(self))
    assert client.get("/wordle/2025-06-12").status_code == 200
    assert len(closed) == 1

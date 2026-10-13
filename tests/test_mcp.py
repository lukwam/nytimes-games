"""MCP server tests, through an in-process MCP client with made-up data."""
import asyncio
import json
from unittest import mock

import pytest
from mcp import Client

from nytgames import NYTGamesAuthenticationError
from nytgames import NYTGamesNotFoundError
from nytgames import mcp_server
from nytgames.models import TrophyCase
from nytgames.models import WordleBotSummary
from tests.test_cli_tables import CONNECTIONS
from tests.test_cli_tables import STATS
from tests.test_cli_tables import WORDLE
from tests.test_formats import puzzle as crossword_puzzle
from tests.test_wordlebot import SUMMARY


@pytest.fixture
def nyt(monkeypatch):
    """Replace the server's NYT client with a mock."""
    fake = mock.Mock()
    fake.wordle.return_value = WORDLE
    fake.connections.return_value = CONNECTIONS
    fake.crossword.return_value = crossword_puzzle()
    fake.crossword_by_id.return_value = crossword_puzzle()
    fake.player_stats.return_value = STATS
    fake.wordlebot_summary.return_value = WordleBotSummary(**SUMMARY)
    fake.wordlebot.return_value = None
    monkeypatch.setattr(mcp_server, "client", lambda: fake)
    return fake


def call(name, arguments=None):
    async def run():
        async with Client(mcp_server.server) as client:
            return await client.call_tool(name, arguments or {})
    return asyncio.run(run())


def data(result):
    assert not result.is_error, result.content[0].text
    content = result.structured_content
    return content["result"] if set(content) == {"result"} else content


def test_tools_are_listed_with_descriptions_and_annotations():
    async def run():
        async with Client(mcp_server.server) as client:
            return (await client.list_tools()).tools
    tools = {t.name: t for t in asyncio.run(run())}
    assert set(tools) == {
        "wordle", "connections", "strands", "spelling_bee", "letter_boxed", "crossword", "wordlebot_summary",
        "puzzle_archive", "stats", "today", "crossword_history", "wordle_history", "spelling_bee_history",
        "wordlebot", "badges", "bonus_week", "bonus_puzzle", "bonus_history", "export_crossword",
    }
    for name, t in tools.items():
        assert t.description and len(t.description) > 40, name
        assert t.annotations.read_only_hint is (name != "export_crossword"), name
    # With overwrite, export_crossword can replace a file.
    assert tools["export_crossword"].annotations.destructive_hint is True
    assert tools["crossword"].input_schema["properties"]["type"]["enum"] == ["daily", "mini", "midi", "bonus"]


def test_answers_are_hidden_unless_asked(nyt):
    assert "solution" not in data(call("wordle", {"date": "2026-10-04"}))
    assert data(call("wordle", {"date": "2026-10-04", "include_answers": True}))["solution"] == "shack"
    assert "categories" not in data(call("connections"))
    assert len(data(call("connections", {"include_answers": True}))["categories"]) == 4


def test_crossword_entries(nyt):
    hidden = data(call("crossword", {"type": "mini", "date": "2025-06-12"}))
    assert hidden["grid"] == ["...", ".#.", "..."]
    assert hidden["entries"][0] == {"id": "1-Across", "direction": "Across", "clue": "First “row”", "length": 3,
                                    "start": [0, 0], "crossings": ["1-Down", "2-Down"]}
    shown = data(call("crossword", {"type": "mini", "date": "2025-06-12", "include_answers": True}))
    assert shown["grid"][0] == "ABC" and shown["entries"][1]["answer"] == "FGHH"
    data(call("crossword", {"puzzle_id": 20759}))
    nyt.crossword_by_id.assert_called_with(20759)


def test_errors_are_actionable(nyt):
    nyt.player_stats.side_effect = NYTGamesAuthenticationError("403", response=mock.Mock(status_code=403))
    result = call("stats")
    assert result.is_error and "nytg auth login" in result.content[0].text

    nyt.wordle.side_effect = NYTGamesNotFoundError("404", response=mock.Mock(status_code=404))
    assert "Not found" in call("wordle", {"date": "1900-01-01"}).content[0].text
    assert "Invalid date" in call("connections", {"date": "someday"}).content[0].text


def test_stats_and_wordlebot(nyt):
    stats = data(call("stats"))
    assert stats["summary"][0]["game"] == "Wordle" and "wordle" in stats["details"]
    bot = data(call("wordlebot"))
    assert "you" not in bot and bot["everyone"]["average_guesses"] == 4.08
    assert "bot_paths" in data(call("wordlebot_summary", {"date": "2026-10-04", "include_answers": True}))


def test_export_crossword(nyt, tmp_path):
    path = tmp_path / "mini.puz"
    result = data(call("export_crossword", {"path": str(path), "type": "mini", "date": "2025-06-12"}))
    assert path.read_bytes()[2:14] == b"ACROSS&DOWN\0"
    assert result["format"] == "puz" and "1 shaded square is shown as a circle" in result["notes"]

    assert "already exists" in call("export_crossword", {"path": str(path)}).content[0].text
    assert "Use a path ending" in call("export_crossword", {"path": str(tmp_path / "x.pdf")}).content[0].text
    nyt.crossword.return_value = crossword_puzzle(**{"body.0.cells.0.label": "CW"})
    failed = call("export_crossword", {"path": str(tmp_path / "x.ipuz")})
    assert failed.is_error and "squares labeled with text" in failed.content[0].text


def test_export_never_replaces_a_file_created_during_the_fetch(nyt, tmp_path):
    """overwrite=False holds when the file appears after the first check (#46)."""
    path = tmp_path / "race.puz"

    def created_meanwhile(*args, **kwargs):
        path.write_bytes(b"USER_FILE_CREATED_DURING_FETCH")
        return crossword_puzzle()

    nyt.crossword.side_effect = created_meanwhile
    result = call("export_crossword", {"path": str(path), "type": "mini", "date": "2025-06-12"})
    assert result.is_error and "already exists" in result.content[0].text
    assert path.read_bytes() == b"USER_FILE_CREATED_DURING_FETCH"


def test_export_overwrite_replaces_the_file(nyt, tmp_path):
    path = tmp_path / "mini.puz"
    path.write_bytes(b"old")
    data(call("export_crossword", {"path": str(path), "overwrite": True}))
    assert path.read_bytes()[2:14] == b"ACROSS&DOWN\0"
    assert [p.name for p in tmp_path.iterdir()] == ["mini.puz"]


def test_cookies_come_from_the_environment_then_the_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("NYTG_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("NYTG_PROFILE", raising=False)
    (tmp_path / "config.ini").write_text("[default]\ncookies = NYT-S=fromprofile\n")
    monkeypatch.delenv("NYT_COOKIES", raising=False)
    assert mcp_server.client().cookies == {"NYT-S": "fromprofile"}
    monkeypatch.setenv("NYT_COOKIES", json.dumps([{"name": "NYT-S", "value": "fromenv"}]))
    assert mcp_server.client().cookies == {"NYT-S": "fromenv"}


def test_cookie_errors_never_show_values(monkeypatch):
    monkeypatch.setenv("NYT_COOKIES", "NYT-S=SECRET\nVALUE")
    result = call("wordle")
    assert result.is_error and "SECRET" not in result.content[0].text


def test_badges(nyt):
    nyt.badges.return_value = TrophyCase(trophies={"wordleV2": {"earned": [{"id": "wr6", "badge_type": "streak",
                                                                            "levels": [7, 14], "earned_at": [1]}]}})
    rows = data(call("badges", {"game": "wordle"}))
    assert [(r["game"], r["name"], r["next_level"]) for r in rows] == [("Wordle", "7-day Streak", 14)]
    nyt.badges.assert_called_once_with(["wordleV2"])


def test_bonus_puzzle_hides_answers(nyt):
    from nytgames.models import BonusWeek
    from nytgames.models import WordleInOnePuzzle
    from tests.support import load
    nyt.bonus_week.return_value = BonusWeek(**load("bonus/week_2026-10-07.json")["bonus_puzzles_week"])
    nyt.bonus_puzzle.return_value = WordleInOnePuzzle(**load("bonus/wordle_in_one_2026-10-07-8.json"))
    assert data(call("bonus_puzzle", {"game": "wordle-in-one"}))["rounds"][0] == {"start": "corgi"}
    shown = data(call("bonus_puzzle", {"game": "wordle-in-one", "include_answers": True}))
    assert shown["rounds"][0]["solution"] == "grace"
    assert call("bonus_puzzle", {"game": "easy"}).is_error

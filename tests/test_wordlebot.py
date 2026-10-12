"""WordleBot tests, with NYT mocked.

Analyses are made up; the day's summary is a real NYT response from tests/fixtures.
"""
import datetime
import json
from unittest import mock as unittest_mock

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from nytgames import api as api_module
from nytgames.cli import app as cli_app
from nytgames.cli import dates
from nytgames.cli import output
from nytgames.cli.state import State
from nytgames.models import WordleBotSummary
from nytgames.models import WordlePuzzle
from tests.support import COOKIES
from tests.support import NYT
from tests.support import load

ENTRY = {
    "response_id": "2", "project_version": "1933", "created_at": "2026-10-04T22:46:51.624Z",
    "element_label": "wordle-gameplay",
    "content": {"gameNumber": 1933, "guesses": "adieu-smart-spank-shack", "mode": "hard", "luck": 0.43,
                "efficiency": 0.93, "luckByRound": [0.06, 0.47, 0.46, 0.75],
                "efficiencyByRound": [0.6, 0.93, 0.86, 1], "solution": "shack", "solutionsRemaining": 1},
}
SUMMARY = {
    "average": {"normal": 4.08, "hard": 3.93}, "efficiency": {"normal": 0.84, "hard": 0.91},
    "luck": {"normal": 0.57, "hard": 0.57}, "steps": {"normal": [1, 2, 3, 4, 5, 6, 7], "hardUsers": 152106,
                                                      "normalUsers": 441594, "hard": [1, 2, 3, 4, 5, 6, 7]},
    "percentSolvingInThreeOrFewer": {"normal": 0.31, "hard": 0.11},
    "percentiles": {"hard": {"p5": 0.77, "p25": 0.87, "p75": 0.96, "p95": 1}},
    "guesses": {"normal-simple": ["slate", "prank", "shack"]},
}


WORDLEBOT_URL = f"{NYT}/svc/int/run/cubby/public-api/v1/responses/wordlebot/reader"
SUMMARY_URL = "https://static01.nyt.com/newsgraphics/2022/wordlebot/vixen-2025-06-12/summary.json"
VIXEN_SUMMARY = load("wordlebot/summary_vixen_2025-06-12.json")
WORDLE = load("wordle/2025-06-12.json")


async def test_wordlebot_returns_the_latest_analysis(logged_in, mock):
    older = {**ENTRY, "response_id": "1", "created_at": "2026-10-04T22:46:35.341Z",
             "content": {**ENTRY["content"], "luck": 0.1}}
    route = mock.get(WORDLEBOT_URL).respond(json=[older, ENTRY])
    analysis = await logged_in("wordlebot")
    assert analysis.response_id == "2" and analysis.luck == 0.43
    assert analysis.guess_list == ["adieu", "smart", "spank", "shack"]
    assert route.call_count == 1
    assert route.calls.last.request.headers["Cookie"] == f"NYT-S={COOKIES['NYT-S']}"


async def test_wordlebot_none_before_opening_it(logged_in, mock):
    mock.get(WORDLEBOT_URL).respond(json=[])
    assert await logged_in("wordlebot") is None


async def test_wordlebot_summary_never_sends_cookies(logged_in, mock):
    route = mock.get(SUMMARY_URL).respond(json=VIXEN_SUMMARY)
    summary = await logged_in("wordlebot_summary", "2025-06-12", solution="vixen")
    assert summary.guesses["normal-simple"] == ["slate", "diner", "given", "vixen"]
    assert summary.average == {"normal": 4.410192374030687, "hard": 4.219190676325831}
    assert len(mock.calls) == 1 and route.call_count == 1
    assert "Cookie" not in route.calls.last.request.headers


async def test_wordlebot_summary_looks_up_the_solution(api, mock):
    wordle = mock.get(f"{NYT}/svc/wordle/v2/2025-06-12.json").respond(json=WORDLE)
    summary = mock.get(SUMMARY_URL).respond(json=VIXEN_SUMMARY)
    await api("wordlebot_summary", "2025-06-12")
    assert wordle.call_count == 1 and summary.call_count == 1
    assert [str(call.request.url) for call in mock.calls] == [f"{NYT}/svc/wordle/v2/2025-06-12.json", SUMMARY_URL]


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("NYTG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("NYT_COOKIES", "NYT-S=abc")
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setattr(dates, "today", lambda: datetime.date(2026, 10, 4))
    output.default_format = None
    client = unittest_mock.Mock()
    client.wordle.return_value = WordlePuzzle(id=1, days_since_launch=1933, print_date="2026-10-04", solution="shack")
    client.wordlebot_summary.return_value = WordleBotSummary(**SUMMARY)
    from nytgames.models import WordleBotAnalysis
    client.wordlebot.return_value = WordleBotAnalysis(**ENTRY["content"])
    monkeypatch.setattr(State, "client", lambda self: client)
    return client


def test_cli_compares_you_with_everyone(cli):
    result = CliRunner().invoke(cli_app.app, ["wordlebot"])
    assert result.exit_code == 0, result.output
    for text in ("hard mode", "You", "Everyone", "93", "91", "SPANK", "between the 25th and 75th percentiles"):
        assert text in result.output
    assert "SLATE" not in result.output  # bot paths are spoilers

    data = json.loads(CliRunner().invoke(cli_app.app, ["wordlebot", "-f", "json"]).stdout)
    assert data["you"]["skill_percentile_range"] == [25, 75]
    assert "bot_paths" not in data


def test_cli_other_days_show_everyone_and_paths_with_answers(cli):
    result = CliRunner().invoke(cli_app.app, ["wordlebot", "yesterday", "--answers"])
    assert result.exit_code == 0, result.output
    assert "You" not in result.output and "SLATE → PRANK → SHACK" in result.output
    cli.wordlebot.assert_not_called()


def test_api_routes(mock):
    route = mock.get(WORDLEBOT_URL)
    route.respond(json=[ENTRY])
    assert TestClient(api_module.app).get("/wordlebot").json()["efficiency"] == 0.93
    route.respond(json=[])
    assert TestClient(api_module.app).get("/wordlebot").json() is None
    assert route.call_count == 2
    mock.get(f"{NYT}/svc/wordle/v2/2025-06-12.json").respond(json=WORDLE)
    mock.get(SUMMARY_URL).respond(json=VIXEN_SUMMARY)
    summary = TestClient(api_module.app).get("/wordlebot/2025-06-12/summary").json()
    assert summary["average"]["hard"] == 4.219190676325831


def test_summary_with_null_percentiles():
    """Early summaries (2021 to early 2022) have null percentiles for a mode."""
    from nytgames.views import skill_rank
    from nytgames.views import wordlebot_view
    summary = WordleBotSummary(**{**SUMMARY, "percentiles": {"normal-ps": None, "hard-ps": None, "hard": None}})
    assert summary.percentiles["hard-ps"] is None
    data = wordlebot_view(datetime.date(2021, 6, 30), WordlePuzzle(id=10, print_date="2021-06-30", solution="shack"),
                          summary)
    assert data["mode"] == "normal" and data["everyone"]["average_guesses"] == 4.08
    assert skill_rank(0.93, summary.percentiles["hard"]) is None

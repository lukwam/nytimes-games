"""WordleBot tests, with made-up data."""
import datetime
import json
from unittest import mock

import pytest
import requests
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from nytgames import NYTGamesClient
from nytgames import api
from nytgames.cli import app as cli_app
from nytgames.cli import dates
from nytgames.cli import output
from nytgames.cli.state import State
from nytgames.models import WordleBotSummary
from nytgames.models import WordlePuzzle

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


@pytest.fixture
def session():
    session = mock.Mock(spec=requests.Session)
    session.get.return_value.raise_for_status.return_value = None
    return session


def test_wordlebot_returns_the_latest_analysis(session):
    older = {**ENTRY, "response_id": "1", "created_at": "2026-10-04T22:46:35.341Z",
             "content": {**ENTRY["content"], "luck": 0.1}}
    session.get.return_value.json.return_value = [older, ENTRY]
    analysis = NYTGamesClient(cookies="NYT-S=abc", session=session).wordlebot()
    assert analysis.response_id == "2" and analysis.luck == 0.43
    assert analysis.guess_list == ["adieu", "smart", "spank", "shack"]
    assert session.get.call_args.kwargs["cookies"] == {"NYT-S": "abc"}


def test_wordlebot_none_before_opening_it(session):
    session.get.return_value.json.return_value = []
    assert NYTGamesClient(cookies="NYT-S=abc", session=session).wordlebot() is None


def test_wordlebot_summary_never_sends_cookies(session):
    session.get.return_value.json.return_value = SUMMARY
    summary = NYTGamesClient(cookies="NYT-S=abc", session=session).wordlebot_summary("2026-10-04", solution="shack")
    assert summary.guesses["normal-simple"][-1] == "shack"
    url = session.get.call_args.args[0]
    assert url == "https://static01.nyt.com/newsgraphics/2022/wordlebot/shack-2026-10-04/summary.json"
    assert session.get.call_args.kwargs["cookies"] is None


def test_wordlebot_summary_looks_up_the_solution(session):
    session.get.return_value.json.side_effect = [
        {"id": 1, "print_date": "2026-10-04", "solution": "shack"}, SUMMARY]
    NYTGamesClient(session=session).wordlebot_summary("2026-10-04")
    assert "shack-2026-10-04" in session.get.call_args.args[0]


@pytest.fixture
def cli(tmp_path, monkeypatch):
    monkeypatch.setenv("NYTG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("NYT_COOKIES", "NYT-S=abc")
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setattr(dates, "today", lambda: datetime.date(2026, 10, 4))
    output.default_format = None
    client = mock.Mock()
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


def test_api_routes():
    with mock.patch.object(api.NYTGamesClient, "_get", side_effect=[[ENTRY]]):
        assert TestClient(api.app).get("/wordlebot").json()["efficiency"] == 0.93
    with mock.patch.object(api.NYTGamesClient, "_get", side_effect=[[]]):
        assert TestClient(api.app).get("/wordlebot").json() is None
    with mock.patch.object(api.NYTGamesClient, "_get",
                           side_effect=[{"id": 1, "print_date": "2026-10-04", "solution": "shack"}, SUMMARY]):
        assert TestClient(api.app).get("/wordlebot/2026-10-04/summary").json()["average"]["hard"] == 3.93



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

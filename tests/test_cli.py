"""nytg command line tests.

The NYT client is replaced with a mock, so these run offline.
"""
import datetime
import json
import stat
import sys
from unittest import mock

import pytest
import requests
from typer.testing import CliRunner

from nytgames import NYTGamesAuthenticationError
from nytgames import NYTGamesNoProfileError
from nytgames import NYTGamesNotFoundError
from nytgames import NYTGamesRateLimitError
from nytgames.cli import app as cli_main
from nytgames.cli import dates
from nytgames.cli import output
from nytgames.cli.state import State
from nytgames.models import ArchivePuzzle
from nytgames.models import ConnectionsLatest
from nytgames.models import ConnectionsPuzzle
from nytgames.models import CrosswordGame
from nytgames.models import CrosswordPuzzlesList
from nytgames.models import Player
from nytgames.models import StrandsLatest
from nytgames.models import TrophyCase
from nytgames.models import WordlePuzzle
from nytgames.models import WordlePuzzlesList

runner = CliRunner()

WORDLE = WordlePuzzle(id=919, days_since_launch=1454, editor="Tracy Bennett",
                      print_date="2025-06-12", solution="vixen")
CONNECTIONS = ConnectionsPuzzle(
    id=1, status="OK", print_date="2025-06-12", editor="Wyna Liu",
    categories=[
        {"title": f"GROUP {g}", "cards": [{"content": f"W{g}{i}", "position": g * 4 + i} for i in range(4)]}
        for g in range(4)
    ],
)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Use a temporary config directory and no cookies from the environment."""
    monkeypatch.setenv("NYTG_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.delenv("NYT_COOKIES", raising=False)
    monkeypatch.delenv("NYTG_PROFILE", raising=False)
    monkeypatch.setattr(dates, "today", lambda: datetime.date(2026, 10, 4))
    output.default_format = None


@pytest.fixture
def client(monkeypatch):
    """Replace the CLI's NYT client with a mock."""
    fake = mock.Mock()
    monkeypatch.setattr(State, "client", lambda self: fake)
    return fake


def run(*args):
    return runner.invoke(cli_main.app, list(args))


@pytest.mark.parametrize("text,expected", [
    ("today", "2026-10-04"),
    ("yesterday", "2026-10-03"),
    ("tomorrow", "2026-10-05"),
    ("sunday", "2026-10-04"),
    ("friday", "2026-10-02"),
    ("2025-06-12", "2025-06-12"),
])
def test_parse_date(text, expected):
    assert dates.parse_date(text).isoformat() == expected


def test_parse_date_first_and_errors():
    assert dates.parse_date("first", "wordle") == datetime.date(2021, 6, 19)
    with pytest.raises(ValueError):
        dates.parse_date("first")
    with pytest.raises(ValueError):
        dates.parse_date("someday")


def test_wordle_hides_the_answer_unless_asked(client):
    client.wordle.return_value = WORDLE

    hidden = json.loads(run("wordle", "2025-06-12", "-f", "json").stdout)
    shown = json.loads(run("wordle", "2025-06-12", "--answers", "-f", "json").stdout)

    assert "solution" not in hidden
    assert shown["solution"] == "vixen"
    client.wordle.assert_called_with("2025-06-12")


def test_value_format(client):
    client.wordle.return_value = WORDLE
    result = run("wordle", "2025-06-12", "-a", "-f", "value(solution,number)")
    assert result.stdout == "vixen\t1454\n"


def test_root_format_option_and_yaml(client):
    client.wordle.return_value = WORDLE
    result = run("-f", "yaml", "wordle", "2025-06-12")
    assert "number: 1454" in result.stdout


def test_connections_board_and_groups(client):
    client.connections.return_value = CONNECTIONS

    board = json.loads(run("connections", "2025-06-12", "-f", "json").stdout)
    groups = json.loads(run("connections", "2025-06-12", "-a", "-f", "json").stdout)

    assert board["board"][0] == ["W00", "W01", "W02", "W03"]
    assert "categories" not in board
    assert groups["categories"][3] == {"title": "GROUP 3", "cards": ["W30", "W31", "W32", "W33"]}


def test_csv_flattens_nested_values(client):
    client.connections.return_value = CONNECTIONS
    result = run("connections", "2025-06-12", "-f", "csv")
    header, row = result.stdout.splitlines()
    assert header == "date,id,editor,board"
    assert row.startswith("2025-06-12,1,Wyna Liu,")


def test_bad_format_fails_before_calling_nyt(client):
    result = run("wordle", "-f", "xml")
    assert result.exit_code == 2
    client.wordle.assert_not_called()


def test_bad_date_is_a_usage_error(client):
    result = run("wordle", "someday")
    assert result.exit_code == 2
    assert "Invalid date" in result.output


@pytest.mark.parametrize("error,message", [
    (NYTGamesNotFoundError("404", response=mock.Mock(status_code=404)), "no puzzle"),
    (NYTGamesAuthenticationError("403", response=mock.Mock(status_code=403)), "nytg auth login"),
    (NYTGamesRateLimitError("429", response=mock.Mock(status_code=429), retry_after=30), "Try again in 30 seconds"),
    (NYTGamesNoProfileError("no profile"), "No NYT Games profile yet"),
])
def test_main_reports_nyt_errors(client, monkeypatch, capsys, error, message):
    client.wordle.side_effect = error
    monkeypatch.setattr(sys, "argv", ["nytg", "wordle", "1900-01-01"])
    with pytest.raises(SystemExit) as exit_info:
        cli_main.main()
    assert exit_info.value.code == 1
    assert message in capsys.readouterr().err


def test_auth_login_saves_only_nyt_s(tmp_path, monkeypatch):
    export = tmp_path / "cookies.json"
    export.write_text(json.dumps([{"name": "NYT-S", "value": "secret"}, {"name": "other", "value": "x"}]))
    with mock.patch("nytgames.cli.settings.NYTGamesClient") as client_class:
        client_class.return_value.player_stats.return_value = Player(user_id=123)
        result = run("auth", "login", "--from-file", str(export))

    assert result.exit_code == 0, result.output
    config = tmp_path / "config" / "config.ini"
    assert "cookies = NYT-S=secret" in config.read_text()
    assert "other" not in config.read_text()
    assert stat.S_IMODE(config.stat().st_mode) == 0o600


def test_auth_login_rejected_cookies_are_not_saved(tmp_path):
    with mock.patch("nytgames.cli.settings.NYTGamesClient") as client_class:
        client_class.return_value.player_stats.side_effect = NYTGamesAuthenticationError(
            "403", response=mock.Mock(status_code=403))
        result = runner.invoke(cli_main.app, ["auth", "login"], input="NYT-S=bad\n")

    assert result.exit_code == 1
    assert not (tmp_path / "config" / "config.ini").exists()


def test_cookie_precedence(monkeypatch):
    state = State()
    state.config.set("default", "cookies", "NYT-S=from-config")
    assert state.resolve_cookies() == ("NYT-S=from-config", "profile 'default'")
    monkeypatch.setenv("NYT_COOKIES", "NYT-S=from-env")
    assert state.resolve_cookies()[1] == "NYT_COOKIES"
    state.cookies = "NYT-S=from-flag"
    assert state.resolve_cookies()[1] == "--cookies"


def test_config_and_profiles():
    assert run("-p", "alice", "config", "set", "format", "json").exit_code == 0
    assert run("-p", "alice", "config", "get", "format").stdout == "json\n"
    assert run("config", "get", "format").exit_code == 1

    assert run("config", "profiles", "activate", "alice").exit_code == 0
    profiles = json.loads(run("config", "profiles", "list", "-f", "json").stdout)
    assert {"name": "alice", "active": True, "cookies": False} in profiles

    assert run("config", "profiles", "delete", "alice").exit_code == 0
    assert run("config", "get", "format").exit_code == 1
    assert run("config", "set", "colour", "red").exit_code == 2


def test_profile_format_is_the_default(client):
    client.wordle.return_value = WORDLE
    run("config", "set", "format", "json")
    assert json.loads(run("wordle", "2025-06-12").stdout)["number"] == 1454


def test_archive_saves_skips_and_reports_missing(client, tmp_path):
    def wordle(day):
        if day == "2025-06-11":
            raise NYTGamesNotFoundError("404", response=mock.Mock(status_code=404))
        return WORDLE

    client.wordle.side_effect = wordle
    out = tmp_path / "archive"
    (out / "wordle").mkdir(parents=True)
    (out / "wordle" / "2025-06-13.json").write_text("{}")

    result = run("archive", "wordle", "--from", "2025-06-11", "--to", "2025-06-13",
                 "-o", str(out), "--delay", "0", "-f", "json")

    summary = json.loads(result.stdout)
    assert (summary["saved"], summary["skipped"], summary["missing"]) == (1, 1, ["2025-06-11"])
    assert json.loads((out / "wordle" / "2025-06-12.json").read_text())["solution"] == "vixen"
    assert (out / "wordle" / "2025-06-13.json").read_text() == "{}"


def test_history_crossword_fetches_the_list_in_windows(client):
    client.crossword_puzzles.return_value = CrosswordPuzzlesList(results=[], status="OK")
    client.crossword_game.return_value = CrosswordGame(user_id=1, states=[])

    result = run("history", "crossword", "--from", "2026-01-01", "--to", "2026-06-30", "-f", "json")

    assert result.exit_code == 0, result.output
    windows = [(c.kwargs["date_start"], c.kwargs["date_end"]) for c in client.crossword_puzzles.call_args_list]
    assert windows == [("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-29"), ("2026-06-30", "2026-06-30")]


def test_history_midi_uses_the_archive_and_game_states(client):
    client.archive.return_value = [ArchivePuzzle(id=23834, print_date="2026-10-04", byline="Paolo Pasco")]
    client.crossword_game.return_value = CrosswordGame(user_id=1, states=[{
        "game": "crossword_midi", "print_date": "2026-10-04", "puzzle_id": "23834",
        "timestamp": 0, "user_id": 1,
        "game_data": {"cells": {}, "firstSolve": 1, "completionFraction": 1, "playTimeSeconds": 227,
                      "star": "gold"},
    }])

    result = run("history", "crossword", "midi", "--from", "2026-10-04", "--to", "2026-10-04", "-f", "json")

    row = json.loads(result.stdout)[0]
    assert (row["solved"], row["seconds"], row["star"], row["author"]) == (True, 227, "gold", "Paolo Pasco")
    client.archive.assert_called_once_with("crossword_midi", "2026-10-04", "2026-10-04")
    client.crossword_puzzles.assert_not_called()
    client.crossword_game.assert_called_once_with([23834], "midi")


def test_history_wordle_uses_the_archive(client):
    client.archive.return_value = [ArchivePuzzle(id=1421, print_date="2026-10-04", solution="shack")]
    client.wordle_latest.return_value = WordlePuzzlesList(user_id=1, states=[{
        "game": "wordleV2", "print_date": "2026-10-04", "puzzle_id": "1421", "timestamp": 0, "user_id": 1,
        "game_data": {"boardState": ["adieu", "shack", "", "", "", ""], "currentRowIndex": 2,
                      "hardMode": True, "status": "WIN"},
    }])

    rows = json.loads(run("history", "wordle", "--from", "2026-10-04", "-f", "json").stdout)

    assert rows == [{"date": "2026-10-04", "puzzle_id": 1421, "status": "win", "guesses": 2,
                     "hard_mode": True, "board": ["adieu", "shack"]}]
    client.wordle.assert_not_called()


def test_history_connections_uses_the_archive(client):
    client.archive.return_value = [ArchivePuzzle(id=1315, print_date="2026-10-04"),
                                   ArchivePuzzle(id=1314, print_date="2026-10-03"),
                                   ArchivePuzzle(id=1313, print_date="2026-10-02")]
    state = {"game": "connections", "print_date": "", "timestamp": 0, "user_id": 1}
    client.connections_latest.return_value = ConnectionsLatest(user_id=1, states=[
        {**state, "puzzle_id": "1315", "game_data": {"mistakes": 1, "puzzleComplete": True, "puzzleWon": True,
                                                     "solvedCategories": [{}, {}, {}, {}]}},
        {**state, "puzzle_id": "1314", "game_data": {"mistakes": 4, "puzzleComplete": True, "puzzleWon": False,
                                                     "solvedCategories": [{}], "isPlayingArchive": True}},
    ])

    rows = json.loads(run("history", "connections", "--from", "2026-10-02", "-f", "json").stdout)

    assert [(r["puzzle_id"], r["status"], r["mistakes"], r["categories_solved"], r["archive"]) for r in rows] == [
        (1315, "won", 1, 4, None), (1314, "lost", 4, 1, True), (1313, "not played", None, 0, None)]
    client.archive.assert_called_once_with("connections", "2026-10-02", "2026-10-04")
    client.connections_latest.assert_called_once_with([1315, 1314, 1313])


def test_history_strands_uses_the_archive(client):
    client.archive.return_value = [ArchivePuzzle(id=1135, print_date="2026-10-04"),
                                   ArchivePuzzle(id=1134, print_date="2026-10-03")]
    client.strands_latest.return_value = StrandsLatest(user_id=1, states=[{
        "game": "strands", "print_date": "2026-10-04", "puzzle_id": "1135", "timestamp": 0, "user_id": 1,
        "game_data": {"isSolved": True, "otherWordsFound": ["CAST", "REEL"], "isPlayingArchive": False},
    }])

    rows = json.loads(run("history", "strands", "--from", "2026-10-03", "-f", "json").stdout)

    assert rows == [
        {"date": "2026-10-04", "puzzle_id": 1135, "status": "solved", "other_words": 2, "archive": False},
        {"date": "2026-10-03", "puzzle_id": 1134, "status": "not played", "other_words": 0, "archive": None},
    ]


def test_cli_extra_message_when_typer_is_missing(monkeypatch):
    import nytgames.cli

    monkeypatch.setitem(sys.modules, "nytgames.cli.app", None)
    with pytest.raises(SystemExit) as exit_info:
        nytgames.cli.main()
    assert "nytimes-games[cli]" in str(exit_info.value)


def test_request_errors_are_reported(client, monkeypatch, capsys):
    client.wordle.side_effect = requests.ConnectionError("offline")
    monkeypatch.setattr(sys, "argv", ["nytg", "wordle"])
    with pytest.raises(SystemExit):
        cli_main.main()
    assert "Request to NYT failed" in capsys.readouterr().err


def test_archive_manifest_and_revisions(client, tmp_path):
    out = tmp_path / "archive"
    client.wordle.return_value = WORDLE
    args = ["archive", "wordle", "--from", "2025-06-12", "--to", "2025-06-12", "-o", str(out), "--delay", "0",
            "-f", "json"]

    assert json.loads(run(*args).stdout)["saved"] == 1
    manifest = json.loads((out / "wordle" / "manifest.json").read_text())["files"]["2025-06-12.json"]
    assert manifest["puzzle_id"] == 919 and len(manifest["sha256"]) == 64 and manifest["retrieved_at"]

    unchanged = json.loads(run(*args, "--overwrite").stdout)
    assert unchanged["updated"] == [] and not (out / "wordle" / "revisions").exists()

    client.wordle.return_value = WORDLE.model_copy(update={"solution": "vixen", "editor": "Fixed"})
    changed = json.loads(run(*args, "--overwrite").stdout)
    assert changed["updated"] == ["2025-06-12"]
    revisions = list((out / "wordle" / "revisions").iterdir())
    assert len(revisions) == 1 and json.loads(revisions[0].read_text())["editor"] == "Tracy Bennett"
    assert json.loads((out / "wordle" / "2025-06-12.json").read_text())["editor"] == "Fixed"
    record = json.loads((out / "wordle" / "manifest.json").read_text())["files"]["2025-06-12.json"]
    assert record["revisions"][0]["file"] == f"revisions/{revisions[0].name}"


def test_nyt_cookies_json_export(monkeypatch):
    """NYT_COOKIES can hold a Cookie-Editor JSON export, as the client accepts."""
    export = json.dumps([{"domain": ".nytimes.com", "name": "NYT-S", "value": "abc="}], indent=2)
    monkeypatch.setenv("NYT_COOKIES", export)
    assert State().client().cookies == {"NYT-S": "abc="}


def test_errors_never_print_cookie_values(monkeypatch, capsys):
    """Unexpected errors print a short message with cookie values redacted, not a traceback."""
    secret = "TOPSECRETCOOKIEVALUE"
    monkeypatch.setenv("NYT_COOKIES", f"NYT-S={secret}")

    def boom(self, *args, **kwargs):
        raise ValueError(f"Invalid header value b'NYT-S={secret}'")

    monkeypatch.setattr("nytgames.client.NYTGamesClient.wordle", boom)
    monkeypatch.setattr(sys, "argv", ["nytg", "wordle", "2025-06-12"])
    with pytest.raises(SystemExit) as exit_info:
        cli_main.main()
    err = capsys.readouterr().err
    assert exit_info.value.code == 1
    assert secret not in err and "Traceback" not in err and "ValueError" in err


def test_malformed_cookie_export_is_redacted(monkeypatch, capsys):
    """Even cookies that can't be parsed are redacted from error output."""
    secret = "TOPSECRETCOOKIEVALUE"
    monkeypatch.setenv("NYT_COOKIES", '[{"name": "NYT-S", "value": "' + secret + '"')
    monkeypatch.setattr(sys, "argv", ["nytg", "wordle", "2025-06-12"])
    with pytest.raises(SystemExit):
        cli_main.main()
    err = capsys.readouterr().err
    assert secret not in err and "couldn't be read as JSON" in err


def test_history_handles_older_game_shapes(client):
    """Rounds-based Wordles and Spelling Bees without a rank still show up."""
    from nytgames.models import ArchivePuzzle
    from nytgames.models import WordlePuzzlesList

    client.archive.return_value = [ArchivePuzzle(id=1, print_date="2022-01-01")]
    client.wordle_latest.return_value = WordlePuzzlesList(user_id=1, states=[{
        "game": "wordleV2", "puzzle_id": "1", "user_id": 1,
        "game_data": {"puzzleComplete": True, "rounds": [{"complete": True}]}}])
    rows = json.loads(run("history", "wordle", "--from", "2022-01-01", "--to", "2022-01-01", "-f", "json").stdout)
    assert rows[0]["status"] == "played" and rows[0]["board"] == []


def test_archive_crosswords_keeps_both_puzzles_on_a_date(client, tmp_path):
    """Crosswords are listed from the archive and fetched by ID; two-puzzle dates get ID file names."""
    from nytgames.models import ArchivePuzzle
    from tests.test_formats import puzzle as crossword_puzzle

    client.archive.return_value = [
        ArchivePuzzle(id=20761, print_date="2022-12-30"),
        ArchivePuzzle(id=20410, print_date="2022-12-31"),
        ArchivePuzzle(id=20759, print_date="2022-12-31"),
    ]
    client.crossword_by_id.side_effect = lambda puzzle_id: crossword_puzzle(id=puzzle_id)
    out = tmp_path / "archive"

    result = json.loads(run("archive", "crossword-daily", "--from", "2022-12-29", "--to", "2022-12-31",
                            "-o", str(out), "--delay", "0", "-f", "json").stdout)

    files = sorted(p.name for p in (out / "crossword-daily").glob("*.json") if p.name != "manifest.json")
    assert files == ["2022-12-30.json", "2022-12-31-20410.json", "2022-12-31-20759.json"]
    assert json.loads((out / "crossword-daily" / "2022-12-31-20759.json").read_text())["id"] == 20759
    assert (result["saved"], result["missing"]) == (3, ["2022-12-29"])
    client.archive.assert_called_once_with("crossword_daily", "2022-12-29", "2022-12-31")
    client.crossword.assert_not_called()


def test_archive_future_crosswords_are_fetched_by_date(client, tmp_path):
    """Tomorrow's crossword isn't in the archive yet, so it's fetched by date."""
    from tests.test_formats import puzzle as crossword_puzzle

    client.archive.return_value = []
    client.crossword.return_value = crossword_puzzle()
    result = json.loads(run("archive", "crossword-mini", "--from", "tomorrow", "--to", "tomorrow",
                            "-o", str(tmp_path), "--delay", "0", "-f", "json").stdout)
    assert result["saved"] == 1
    client.crossword.assert_called_once_with("mini", "2026-10-05")
    client.archive.assert_not_called()


def test_badges(client):
    client.badges.return_value = TrophyCase(trophies={"strands": {
        "earned": [{"id": "st4", "badge_type": "milestone", "levels": [25, 50, 75], "progress": 60,
                    "earned_at": [1759700000, 1759800000], "last_earned_level": 50}],
        "unearned": [{"id": "st4"}, {"id": "st2", "badge_type": "streak", "levels": [7, 14], "progress": 3}],
    }})
    rows = json.loads(run("badges", "strands", "-f", "json").stdout)
    assert [(r["name"], r["earned"], r["level"], r["next_level"], r["last_earned"]) for r in rows] == [
        ("Found Theme Words", True, 50, 75, "2025-10-07"), ("7-Day Streak", False, None, 7, None)]
    client.badges.assert_called_once_with(["strands"])

    earned = json.loads(run("badges", "--earned", "-f", "json").stdout)
    assert [r["id"] for r in earned] == ["st4"]
    assert client.badges.call_args.args[0] == ["wordleV2", "connections", "strands", "spelling_bee"]
    assert "Found Theme Words" in run("badges").stdout

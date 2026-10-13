"""Malformed NYT responses: NYTGamesParseError, never the response's values (#44).

Responses that are valid JSON but the wrong shape become NYTGamesParseError,
naming the model and fields but never the values, which can be your saved
games. Every surface is checked with a made-up private marker: the clients,
the REST API, the MCP server, the CLI and the live check.
"""
import asyncio
import importlib.util
import json
import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from nytgames import NYTGamesClient
from nytgames import NYTGamesParseError
from nytgames import api
from nytgames import mcp_server
from nytgames.models import WordlePuzzle
from nytgames.models import parse
from tests.support import NYT
from tests.support import load

MARKER = "SYNTHETIC_PRIVATE_INPUT"
WORDLE = f"{NYT}/svc/wordle/v2/2025-06-12.json"

MALFORMED = {
    "missing field": {"private": MARKER},
    "wrong nested type": {"id": 1, "print_date": "2025-06-12", "solution": {"private": MARKER}},
    "not an object": [MARKER],
    "not JSON object at all": MARKER,
}


@pytest.mark.parametrize("body", MALFORMED.values(), ids=MALFORMED.keys())
async def test_clients_raise_parse_errors_without_values(api, mock, body):
    mock.get(WORDLE).respond(json=body)
    with pytest.raises(NYTGamesParseError, match="WordlePuzzle") as info:
        await api("wordle", "2025-06-12")
    assert MARKER not in str(info.value)
    # No chained ValidationError, whose traceback could show the values.
    assert info.value.__cause__ is None
    assert info.value.__context__ is None or info.value.__suppress_context__


async def test_nested_lists_and_list_responses(api, mock):
    mock.get(f"{NYT}/svc/connections/v2/2025-06-12.json").respond(json={
        "id": 1, "status": "OK", "print_date": "2025-06-12", "editor": "x", "categories": MARKER})
    with pytest.raises(NYTGamesParseError, match=r"ConnectionsPuzzle: categories: list_type") as info:
        await api("connections", "2025-06-12")
    assert MARKER not in str(info.value)
    mock.get(f"{NYT}/svc/games/v1/archive/wordle/2025-06-12/2025-06-12").respond(json={"private": MARKER})
    with pytest.raises(NYTGamesParseError, match="list of ArchivePuzzle") as info:
        await api("archive", "wordle", "2025-06-12", "2025-06-12")
    assert MARKER not in str(info.value)


def test_messages_name_the_fields_and_error_types():
    with pytest.raises(NYTGamesParseError) as info:
        parse(WordlePuzzle, {"id": "not a number", "print_date": "2025-06-12"})
    assert str(info.value) == "NYT's response didn't match WordlePuzzle: id: int_parsing; solution: missing"


def test_model_validation_errors_hide_values_too():
    """Even a ValidationError raised directly by a model hides the input."""
    with pytest.raises(ValueError) as info:
        WordlePuzzle(id=MARKER, print_date="2025-06-12", solution="abcde")
    assert MARKER not in str(info.value)


def test_rest_api_returns_502_without_values(mock):
    mock.get(WORDLE).respond(json={"private": MARKER})
    response = TestClient(api.app).get("/wordle/2025-06-12")
    assert response.status_code == 502
    assert MARKER not in response.text


def test_mcp_tool_error_and_log_have_no_values(mock, monkeypatch, caplog):
    mock.get(WORDLE).respond(json={"private": MARKER})
    monkeypatch.setattr(mcp_server, "client", lambda: NYTGamesClient(backoff=0))

    async def call():
        async with Client(mcp_server.server) as client:
            return await client.call_tool("wordle", {"date": "2025-06-12"})

    with caplog.at_level(logging.DEBUG):
        result = asyncio.run(call())
    assert result.is_error and "expected format" in result.content[0].text
    assert MARKER not in result.content[0].text
    assert MARKER not in caplog.text


def test_cli_error_has_no_values(mock, tmp_path, monkeypatch, capsys):
    from typer.testing import CliRunner

    from nytgames.cli import app as cli_main
    monkeypatch.setenv("NYTG_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("NYT_COOKIES", raising=False)
    mock.get(WORDLE).respond(json={"private": MARKER})
    monkeypatch.setattr(sys, "argv", ["nytg", "wordle", "2025-06-12"])
    result = CliRunner().invoke(cli_main.app, ["wordle", "2025-06-12"])
    assert result.exit_code != 0
    assert MARKER not in result.output
    with pytest.raises(SystemExit):
        cli_main.main()
    err = capsys.readouterr().err
    assert "Couldn't read NYT's response" in err and "WordlePuzzle" in err
    assert MARKER not in err


@pytest.fixture
def live_check():
    path = Path(__file__).parent.parent / "scripts" / "live_check.py"
    spec = importlib.util.spec_from_file_location("live_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("error", [KeyError(MARKER), TypeError(MARKER), ValueError(MARKER)])
def test_live_check_failures_have_no_values(live_check, capsys, error):
    def check():
        raise error

    result = live_check.run("Check", check)
    assert not result["ok"] and result["detail"].startswith(type(error).__name__ + " in check")
    assert MARKER not in json.dumps(result)
    assert MARKER not in capsys.readouterr().err


def test_live_check_keeps_safe_messages(live_check):
    def check():
        raise NYTGamesParseError("NYT's response didn't match WordlePuzzle: solution: missing")

    assert live_check.run("Check", check)["detail"].endswith("solution: missing")

    def failed_assertion():
        assert False, "31 dailies"

    assert "31 dailies" in live_check.run("Check", failed_assertion)["detail"]


# Keys taken from the response can be private too (#44 follow-up): a
# dictionary key in the response appears in the error's field path.
SUMMARY = "https://static01.nyt.com/newsgraphics/2022/wordlebot/vixen-2025-06-12/summary.json"
KEY_MARKER_BODY = {"average": {MARKER: []}}


def test_field_paths_hide_keys_from_the_response():
    from nytgames.models import WordleBotSummary
    with pytest.raises(NYTGamesParseError) as info:
        parse(WordleBotSummary, KEY_MARKER_BODY)
    assert str(info.value) == "NYT's response didn't match WordleBotSummary: average.*: float_type"


def test_field_paths_keep_field_names_aliases_and_indexes():
    from nytgames.models import ConnectionsPuzzle
    body = {"id": 1, "status": "OK", "print_date": "2025-06-12", "editor": "x",
            "categories": [{"title": "A", "cards": [{"position": "first"}]}]}
    with pytest.raises(NYTGamesParseError, match=r"categories\.0\.cards\.0\.position: int_parsing"):
        parse(ConnectionsPuzzle, body)


@pytest.fixture
def key_marker(mock):
    mock.get(WORDLE).respond(json=load("wordle/2025-06-12.json"))
    mock.get(SUMMARY).respond(json=KEY_MARKER_BODY)
    return mock


async def test_clients_hide_keys_from_the_response(api, key_marker):
    with pytest.raises(NYTGamesParseError, match=r"average\.\*: float_type") as info:
        await api("wordlebot_summary", "2025-06-12")
    assert MARKER not in str(info.value)


def test_rest_mcp_and_cli_hide_keys_from_the_response(key_marker, monkeypatch, tmp_path, caplog, capsys):
    response = TestClient(api.app).get("/wordlebot/2025-06-12/summary")
    assert response.status_code == 502 and MARKER not in response.text

    monkeypatch.setattr(mcp_server, "client", lambda: NYTGamesClient(backoff=0))

    async def call():
        async with Client(mcp_server.server) as client:
            return await client.call_tool("wordlebot_summary", {"date": "2025-06-12"})

    with caplog.at_level(logging.DEBUG):
        result = asyncio.run(call())
    assert result.is_error and MARKER not in result.content[0].text and MARKER not in caplog.text

    from nytgames.cli import app as cli_main
    monkeypatch.setenv("NYTG_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("NYT_COOKIES", raising=False)
    monkeypatch.setattr(sys, "argv", ["nytg", "wordlebot", "2025-06-12"])
    with pytest.raises(SystemExit):
        cli_main.main()
    captured = capsys.readouterr()
    assert "average.*" in captured.err
    assert MARKER not in captured.out + captured.err


def test_live_check_hides_keys_from_the_response(live_check, capsys):
    from nytgames.models import WordleBotSummary

    def check():
        parse(WordleBotSummary, KEY_MARKER_BODY)

    result = live_check.run("Check", check)
    assert not result["ok"] and "average.*" in result["detail"]
    assert MARKER not in json.dumps(result) and MARKER not in capsys.readouterr().err

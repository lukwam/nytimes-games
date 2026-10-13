"""Crossword export tests.

Uses a small made-up puzzle, not NYT content. The .puz output is checked with
puzpy and the .ipuz output with the ipuz package.
"""
import copy
import json
import xml.etree.ElementTree as ET
from unittest import mock

import ipuz
import puz
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from nytgames import NYTGamesExportError
from nytgames.formats import export
from nytgames.formats import export_problems
from nytgames.formats import fidelity
from nytgames.formats import to_grid
from nytgames.formats import to_ipuz
from nytgames.formats import to_puz
from nytgames.formats import to_xml
from nytgames.models import CrosswordGame
from nytgames.models import CrosswordPuzzle

# A B C       1 2 .
# D # E   ->  . # .    (B is circled, G is shaded, the last square is a rebus)
# F G HH      3 . .
PUZZLE = {
    "id": 1,
    "constructors": ["Ann Author"],
    "copyright": "2025",
    "editor": "Ed Editor",
    "lastUpdated": "",
    "publicationDate": "2025-06-12",
    "notes": [{"text": "A note about the puzzle."}],
    "body": [{
        "board": "",
        "SVG": {},
        "dimensions": {"width": 3, "height": 3},
        "cells": [
            {"answer": "A", "clues": [0, 2], "label": "1", "type": 1},
            {"answer": "B", "clues": [0], "type": 2},
            {"answer": "C", "clues": [0, 3], "label": "2", "type": 1},
            {"answer": "D", "clues": [2], "type": 1},
            {},
            {"answer": "E", "clues": [3], "type": 1},
            {"answer": "F", "clues": [1, 2], "label": "3", "type": 1},
            {"answer": "G", "clues": [1], "type": 3},
            {"answer": "HH", "clues": [1, 3], "moreAnswers": {"valid": ["H"]}, "type": 1},
        ],
        "clues": [
            {"cells": [0, 1, 2], "direction": "Across", "label": "1", "text": [{"plain": "First “row”"}]},
            {"cells": [6, 7, 8], "direction": "Across", "label": "3", "text": [{"plain": "Last row…"}]},
            {"cells": [0, 3, 6], "direction": "Down", "label": "1", "text": [{"plain": "Left column"}]},
            {"cells": [2, 5, 8], "direction": "Down", "label": "2", "text": [{"plain": "Right – column"}]},
        ],
        "clueLists": [{"name": "Across", "clues": [0, 1]}, {"name": "Down", "clues": [2, 3]}],
    }],
}
GAME = CrosswordGame(user_id=1, states=[{
    "game": "crossword_daily", "print_date": "2025-06-12", "puzzle_id": "1", "timestamp": 0, "user_id": 1,
    "game_data": {"cells": {"0": "A", "1": "B", "2": "X", "8": "HH"}, "playTimeSeconds": 95,
                  "revealed": [1], "penciled": [2]},
}])


def puzzle(**changes) -> CrosswordPuzzle:
    """Return the made-up puzzle, with dotted-path changes such as body.0.cells.0.label."""
    data = copy.deepcopy(PUZZLE)
    for path, value in changes.items():
        target = data
        *parents, last = path.split(".")
        for key in parents:
            target = target[int(key)] if key.isdigit() else target[key]
        target[int(last) if last.isdigit() else last] = value
    return CrosswordPuzzle(**data)


def test_puz_is_valid_and_complete():
    data = to_puz(puzzle())
    p = puz.load(data)

    assert p.tobytes() == data  # puzpy recomputes every checksum
    assert (p.width, p.height) == (3, 3)
    assert p.solution == "ABCD.EFGH"
    assert p.fill == "----.----"
    assert p.title == "New York Times Crossword, June 12, 2025"
    assert (p.author, p.copyright) == ("Ann Author", "© 2025 The New York Times")
    assert p.notes == "A note about the puzzle."
    numbering = p.clue_numbering()
    assert [(c["num"], c["clue"]) for c in numbering.across] == [(1, 'First "row"'), (3, "Last row...")]
    assert [(c["num"], c["clue"]) for c in numbering.down] == [(1, "Left column"), (2, "Right - column")]
    assert p.rebus().get_rebus_solution(8) == "HH"
    assert p.markup().get_markup_squares() == [1, 7]


def test_puz_with_progress():
    p = puz.load(to_puz(puzzle(), GAME))
    assert p.fill == "ABX-.---H"
    assert p.extensions[b"LTIM"] == b"95,1"
    assert p.markup().markup[1] & 0x40  # revealed


def test_ipuz_is_valid_and_complete():
    document = to_ipuz(puzzle(), GAME)
    ipuz.read(json.dumps(document))

    assert document["puzzle"] == [[1, {"cell": 0, "style": {"shapebg": "circle"}}, 2],
                                  [0, "#", 0],
                                  [3, {"cell": 0, "style": {"color": "D3D3D3"}}, 0]]
    assert document["solution"] == [["A", "B", "C"], ["D", "#", "E"], ["F", "G", "HH"]]
    assert document["saved"] == [["A", "B", "X"], [0, "#", 0], [0, 0, "HH"]]
    assert document["clues"]["Across"] == [[1, "First “row”"], [3, "Last row…"]]
    assert document["date"] == "06/12/2025"


def test_xml_is_complete():
    root = ET.fromstring(to_xml(puzzle(), GAME, title="My title"))
    ns = {"x": "http://crossword.info/xml/rectangular-puzzle"}

    assert root.find("x:metadata/x:title", ns).text == "My title"
    cells = root.findall("x:crossword/x:grid/x:cell", ns)
    assert len(cells) == 9
    assert cells[4].get("type") == "block"
    assert cells[1].get("background-shape") == "circle"
    assert cells[1].get("solve-status") == "revealed"
    assert cells[2].get("solve-state") == "X" and cells[2].get("solve-status") == "pencil"
    assert cells[7].get("background-color") == "#D3D3D3"
    assert cells[8].get("solution") == "HH"
    words = root.findall("x:crossword/x:word", ns)
    assert [(w.get("x"), w.get("y")) for w in words] == [("1-3", "1"), ("1-3", "3"), ("1", "1-3"), ("3", "1-3")]
    clues = root.findall("x:crossword/x:clues/x:clue", ns)
    assert [(c.get("word"), c.get("number"), c.text) for c in clues][0] == ("1", "1", "First “row”")


@pytest.mark.parametrize("changes,reason", [
    ({"body.0.cells.0.label": "CW"}, "squares labeled with text (CW)"),
    ({"body.0.clues.0.label": None}, "clues without numbers"),
    ({"body.0.clueLists": [{"name": "Across", "clues": [0, 1]}, {"name": "Down", "clues": [2, 3]},
                           {"name": "Around", "clues": []}]}, "clues in a 'Around' list"),
    ({"body.0.clues.0.cells": [0, 1, 3]}, "1-Across isn't a straight across entry"),
])
def test_gimmicks_cant_be_exported(changes, reason):
    p = puzzle(**changes)
    for fmt in ("ipuz", "puz", "xml"):
        with pytest.raises(NYTGamesExportError) as info:
            export(p, fmt)
        assert reason in info.value.reasons
        assert export_problems(p, fmt) == info.value.reasons


def test_puz_rejects_text_it_cant_store():
    p = puzzle(**{"body.0.clues.0.text": [{"plain": "I ♥ NY"}]})
    assert export_problems(p, "puz") == ["clues with characters .puz can't store (♥)"]
    assert export_problems(p, "ipuz") == []


def test_unknown_format():
    with pytest.raises(ValueError):
        export(puzzle(), "pdf")


def test_cli_save(tmp_path, monkeypatch):
    from nytgames.cli import app as cli_app
    from nytgames.cli.state import State

    client = mock.Mock()
    client.crossword.return_value = puzzle()
    client.crossword_game.return_value = GAME
    monkeypatch.setattr(State, "client", lambda self: client)
    monkeypatch.setenv("NYTG_CONFIG_DIR", str(tmp_path / "config"))
    runner = CliRunner()

    result = runner.invoke(cli_app.app, ["crossword", "mini", "2025-06-12", "--save", str(tmp_path / "m.puz"),
                                         "--progress"])
    assert result.exit_code == 0, result.output
    p = puz.read(str(tmp_path / "m.puz"))
    assert p.title == "NYT Mini Crossword, June 12, 2025" and p.fill == "ABX-.---H"

    assert runner.invoke(cli_app.app, ["crossword", "--save", str(tmp_path / "m.pdf")]).exit_code == 2
    client.crossword.return_value = puzzle(**{"body.0.cells.0.label": "CW"})
    result = runner.invoke(cli_app.app, ["crossword", "--save", str(tmp_path / "x.ipuz")])
    assert result.exit_code == 1 and "squares labeled with text" in result.output


def test_api_download(monkeypatch):
    from nytgames import api

    with mock.patch.object(api.NYTGamesClient, "crossword", return_value=puzzle()):
        client = TestClient(api.app)
        response = client.get("/crosswords/mini/2025-06-12/download")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/x-crossword"
        assert 'filename="nyt-mini-2025-06-12.puz"' in response.headers["content-disposition"]
        assert puz.load(response.content).solution == "ABCD.EFGH"
        assert client.get("/crosswords/mini/2025-06-12/download?format=ipuz").json()["dimensions"]["width"] == 3

    with mock.patch.object(api.NYTGamesClient, "crossword",
                           return_value=puzzle(**{"body.0.cells.0.label": "CW"})):
        response = TestClient(api.app).get("/crosswords/mini/2025-06-12/download")
        assert response.status_code == 422
        assert "squares labeled with text (CW)" in response.json()["detail"]["reasons"]


def test_fidelity():
    p = puzzle(**{"body.0.clues.0.text": [{"plain": "In italics", "formatted": "In <i>italics</i>"}]})
    assert fidelity(p, "ipuz") == ["clue formatting such as italics is dropped (1 clue)",
                                   "other accepted answers for rebus squares aren't kept"]
    puz_notes = fidelity(p, "puz", GAME)
    assert "1 shaded square is shown as a circle" in puz_notes
    assert "typographic punctuation is converted to plain text (– …)" in puz_notes
    assert "penciled squares aren't marked" in puz_notes
    assert "the timer isn't kept" in fidelity(p, "xml", GAME)
    with pytest.raises(NYTGamesExportError):
        fidelity(puzzle(**{"body.0.cells.0.label": "CW"}), "ipuz")


def progress(cells=None, **extra) -> CrosswordGame:
    """The made-up saved game, with these cells and other game_data fields."""
    return CrosswordGame(user_id=1, states=[{
        "game": "crossword_daily", "print_date": "2025-06-12", "puzzle_id": "1", "timestamp": 0, "user_id": 1,
        "game_data": {"cells": cells if cells is not None else {}, **extra},
    }])


@pytest.mark.parametrize("cells", [
    {"-1": "X"},           # used to fill the last square
    {"-100": "X"},         # used to raise IndexError
    {"nonnumeric": "X"},   # used to raise ValueError
    {"9": "X"}, {"10000000000000000000000": "X"}, {" 1": "X"}, {"1.0": "X"}, {"١": "X"},
])
def test_progress_skips_cells_that_name_no_square(cells):
    """Saved progress can't fill another square or break the export (#67)."""
    grid = to_grid(puzzle(), progress(cells))
    assert [square.fill for square in grid.squares] == [""] * 9


@pytest.mark.parametrize("marks", [
    [-1], [-100], [9], ["-1"], [1.0], [True], [None], [[1]], [{"x": 1}], "1", 1, {"1": True}, None,
])
def test_progress_skips_marks_that_name_no_square(marks):
    grid = to_grid(puzzle(), progress(revealed=marks, penciled=marks))
    assert not any(square.revealed or square.penciled for square in grid.squares)


def test_progress_with_valid_indexes_still_works():
    grid = to_grid(puzzle(), progress({"0": "A", 1: "B", "8": "HH"}, revealed=[1, 1], penciled=[2]))
    assert [square.fill for square in grid.squares][:3] == ["A", "B", ""] and grid.squares[8].fill == "HH"
    assert [i for i, s in enumerate(grid.squares) if s.revealed] == [1]
    assert [i for i, s in enumerate(grid.squares) if s.penciled] == [2]
    assert export(puzzle(), "puz", progress({"-1": "X", "0": "A"}))  # every format still exports

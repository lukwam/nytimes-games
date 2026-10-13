"""Export NYT crosswords to standard crossword file formats.

- ``ipuz``: the open JSON format (http://ipuz.org)
- ``puz``: Across Lite's binary format, the most widely supported
- ``xml``: Crossword Compiler's rectangular-puzzle XML
  (https://crossword.info/xml/rectangular-puzzle.xsd)

Pass the user's saved game to include their progress: the letters they've
filled in, revealed and penciled squares, and (in .puz) the timer.

Puzzles with gimmicks the formats can't represent, such as squares labeled
with text or clues that wind around the grid, raise NYTGamesExportError
with the reasons. Use ``export_problems()`` to check without exporting, and
``fidelity()`` to see what an export approximates, such as shading shown as
circles in .puz.

NYT puzzles are copyrighted by The New York Times; exported files are for
personal use.
"""
import datetime
import json
import re
import struct
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from dataclasses import field

from nytgames.exceptions import NYTGamesExportError
from nytgames.models import CrosswordGame
from nytgames.models import CrosswordGameData
from nytgames.models import CrosswordGameState
from nytgames.models import CrosswordPuzzle

FORMATS = ("ipuz", "puz", "xml")
MEDIA_TYPES = {
    "ipuz": "application/json",
    "puz": "application/x-crossword",
    "xml": "application/xml",
}
SHADE_COLOR = "D3D3D3"
CIRCLED = 2
SHADED = 3

Game = CrosswordGame | CrosswordGameState | CrosswordGameData | None


@dataclass
class Square:
    """One square of the grid."""
    block: bool
    solution: str = ""
    label: int | None = None
    circled: bool = False
    shaded: bool = False
    fill: str = ""
    revealed: bool = False
    penciled: bool = False


@dataclass
class Clue:
    number: int
    text: str
    cells: list[int]


@dataclass
class Grid:
    """A crossword in a format-neutral shape."""
    width: int
    height: int
    squares: list[Square]
    across: list[Clue]
    down: list[Clue]
    title: str
    author: str
    editor: str
    copyright: str
    date: datetime.date
    notes: str
    puzzle_id: int = 0
    seconds: int | None = None
    problems: list[str] = field(default_factory=list)

    def xy(self, index: int) -> tuple[int, int]:
        """Return the (column, row) of a square, from 0."""
        return index % self.width, index // self.width


def _square_index(value, count: int) -> int | None:
    """Return a saved-progress index as a square number, or None unless it's
    a non-negative whole number (or string of digits) less than `count`."""
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < count:
        return value
    return None


def game_data(game: Game) -> CrosswordGameData | None:
    """Return the saved game data from any of the game state models."""
    if isinstance(game, CrosswordGame):
        return game.states[0].game_data if game.states else None
    if isinstance(game, CrosswordGameState):
        return game.game_data
    return game


def clue_text(clue) -> str:
    return "".join(part.get("plain", "") for part in clue.text)


def straight(cells: list[int], width: int, step: int) -> bool:
    """Return whether cells run in a straight line with the given step."""
    if step == 1 and len({c // width for c in cells}) != 1:
        return False
    return all(b - a == step for a, b in zip(cells, cells[1:]))


def to_grid(puzzle: CrosswordPuzzle, game: Game = None, title: str | None = None) -> Grid:
    """Convert a puzzle (and optional saved game) to a Grid, noting gimmicks."""
    body = puzzle.body[0]
    width, height = body.dimensions["width"], body.dimensions["height"]
    problems = []
    squares = []
    text_labels = []
    for cell in body.cells:
        if not cell.type:
            squares.append(Square(block=True))
            continue
        if isinstance(cell.label, str):
            text_labels.append(cell.label)
        squares.append(Square(
            block=False,
            solution=cell.answer or "",
            label=cell.label if isinstance(cell.label, int) else None,
            circled=cell.type == CIRCLED,
            shaded=cell.type == SHADED,
        ))
    if text_labels:
        problems.append(f"squares labeled with text ({' '.join(dict.fromkeys(text_labels))})")
    if len(squares) != width * height:
        problems.append("a grid that isn't rectangular")

    lists = {"across": [], "down": []}
    for clue_list in body.clueLists:
        name = clue_list.name.lower()
        if name not in lists:
            problems.append(f"clues in a {clue_list.name!r} list")
            continue
        step = 1 if name == "across" else width
        for index in clue_list.clues:
            clue = body.clues[index]
            if not (clue.label or "").isdigit():
                problems.append("clues without numbers")
                continue
            if not straight(clue.cells, width, step):
                problems.append(f"{clue.label}-{clue_list.name} isn't a straight {clue_list.name.lower()} entry")
                continue
            lists[name].append(Clue(int(clue.label), clue_text(clue), clue.cells))

    data = game_data(game)
    if data is not None:
        # Saved progress is optional: entries that don't name a square of
        # this grid, such as negative or non-numeric indexes, are skipped.
        extra = data.model_extra or {}
        cells = data.cells if isinstance(data.cells, dict) else {}
        for key, value in cells.items():
            index = _square_index(key, len(squares))
            if index is not None and not squares[index].block and isinstance(value, str):
                squares[index].fill = value
        for name in ("revealed", "penciled"):
            marked = extra.get(name)
            for item in marked if isinstance(marked, list) else []:
                index = _square_index(item, len(squares))
                if index is not None:
                    setattr(squares[index], name, True)

    date = datetime.date.fromisoformat(puzzle.publicationDate)
    notes = " ".join(
        note.get("text", "") for note in (puzzle.notes or []) if isinstance(note, dict)
    ).strip()
    return Grid(
        width=width,
        height=height,
        squares=squares,
        across=lists["across"],
        down=lists["down"],
        title=title or puzzle.title or f"New York Times Crossword, {date:%B} {date.day}, {date.year}",
        author=", ".join(puzzle.constructors),
        editor=puzzle.editor or "",
        copyright=f"© {puzzle.copyright} The New York Times",
        date=date,
        notes=notes,
        puzzle_id=puzzle.id,
        seconds=data.playTimeSeconds if data is not None else None,
        problems=list(dict.fromkeys(problems)),
    )


def check(grid: Grid, fmt: str) -> None:
    if grid.problems:
        raise NYTGamesExportError(fmt, grid.problems)


def export_problems(puzzle: CrosswordPuzzle, fmt: str) -> list[str]:
    """Return why a puzzle can't be exported to a format, or [] if it can."""
    try:
        export(puzzle, fmt)
    except NYTGamesExportError as err:
        return err.reasons
    return []


def plural(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def fidelity(puzzle: CrosswordPuzzle, fmt: str, game: Game = None) -> list[str]:
    """Return what exporting to a format approximates or leaves out.

    An empty list means the export keeps everything. Raises
    NYTGamesExportError if the puzzle can't be exported at all.
    """
    export(puzzle, fmt, game)
    grid = to_grid(puzzle, game)
    body = puzzle.body[0]
    notes = []

    formatted = sum(
        1 for clue in body.clues
        if any(re.search(r"<\s*[a-zA-Z]", part.get("formatted", "")) for part in clue.text)
    )
    if formatted:
        notes.append(f"clue formatting such as italics is dropped ({plural(formatted, 'clue')})")
    if any(cell.moreAnswers for cell in body.cells):
        notes.append("other accepted answers for rebus squares aren't kept")

    shaded = sum(square.shaded for square in grid.squares)
    revealed = any(square.revealed for square in grid.squares)
    penciled = any(square.penciled for square in grid.squares)
    if fmt == "puz":
        if shaded:
            notes.append("1 shaded square is shown as a circle" if shaded == 1
                         else f"{shaded} shaded squares are shown as circles")
        texts = [grid.title, grid.notes] + [clue.text for clue in grid.across + grid.down]
        converted = sorted({ch for text in texts for ch in text if ch in PUNCTUATION_CHARACTERS})
        if converted:
            notes.append(f"typographic punctuation is converted to plain text ({' '.join(converted)})")
        if any(len(square.fill) > 1 for square in grid.squares):
            notes.append("rebus squares you filled in keep only their first letter")
        if penciled:
            notes.append("penciled squares aren't marked")
    if fmt == "ipuz":
        if revealed or penciled:
            notes.append("revealed and penciled squares aren't marked")
        if grid.seconds is not None:
            notes.append("the timer isn't kept")
    if fmt == "xml" and grid.seconds is not None:
        notes.append("the timer isn't kept")
    return notes


def export(puzzle: CrosswordPuzzle, fmt: str, game: Game = None, title: str | None = None) -> bytes:
    """Export a puzzle to ipuz, puz or xml, as the bytes of the file."""
    if fmt == "ipuz":
        return json.dumps(to_ipuz(puzzle, game, title), ensure_ascii=False, indent=2).encode() + b"\n"
    if fmt == "puz":
        return to_puz(puzzle, game, title)
    if fmt == "xml":
        return to_xml(puzzle, game, title).encode()
    raise ValueError(f"Unknown format {fmt!r}; use one of {', '.join(FORMATS)}")


# ipuz


def to_ipuz(puzzle: CrosswordPuzzle, game: Game = None, title: str | None = None) -> dict:
    """Return the puzzle as an ipuz document (a dict to save as JSON)."""
    grid = to_grid(puzzle, game, title)
    check(grid, "ipuz")

    def rows(values):
        return [values[r * grid.width:(r + 1) * grid.width] for r in range(grid.height)]

    cells = []
    for square in grid.squares:
        if square.block:
            cells.append("#")
            continue
        style = {}
        if square.circled:
            style["shapebg"] = "circle"
        if square.shaded:
            style["color"] = SHADE_COLOR
        cells.append({"cell": square.label or 0, "style": style} if style else square.label or 0)

    document = {
        "version": "http://ipuz.org/v2",
        "kind": ["http://ipuz.org/crossword#1"],
        "title": grid.title,
        "author": grid.author,
        "editor": grid.editor,
        "copyright": grid.copyright,
        "publisher": "The New York Times",
        "date": f"{grid.date:%m/%d/%Y}",
        "origin": "nytimes-games",
        "dimensions": {"width": grid.width, "height": grid.height},
        "block": "#",
        "empty": 0,
        "puzzle": rows(cells),
        "solution": rows(["#" if s.block else s.solution for s in grid.squares]),
        "clues": {
            "Across": [[clue.number, clue.text] for clue in grid.across],
            "Down": [[clue.number, clue.text] for clue in grid.down],
        },
    }
    if grid.notes:
        document["notes"] = grid.notes
    if game is not None:
        document["saved"] = rows(["#" if s.block else s.fill or 0 for s in grid.squares])
    return document


# Across Lite .puz

PUNCTUATION_MAP = {
    "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "--", "…": "...", "\u00a0": " ",
}
PUNCTUATION = str.maketrans(PUNCTUATION_MAP)
PUNCTUATION_CHARACTERS = set(PUNCTUATION_MAP) - {"\u00a0"}


def latin1(text: str, what: str, problems: list[str]) -> bytes:
    """Encode text as .puz's Latin-1, replacing common typographic punctuation."""
    text = unicodedata.normalize("NFC", text.translate(PUNCTUATION))
    try:
        return text.encode("latin-1")
    except UnicodeEncodeError:
        bad = sorted({ch for ch in text if ord(ch) > 255})
        problems.append(f"{what} with characters .puz can't store ({''.join(bad)})")
        return b""


def checksum(data: bytes, value: int = 0) -> int:
    """The .puz checksum."""
    for byte in data:
        value = ((value >> 1) | 0x8000) if value & 1 else value >> 1
        value = (value + byte) & 0xFFFF
    return value


def numbering(grid: Grid) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Return the (number, first square) of each across and down entry, as .puz numbers them."""
    across, down = [], []
    number = 0
    for index, square in enumerate(grid.squares):
        if square.block:
            continue
        x, y = grid.xy(index)
        starts_across = (x == 0 or grid.squares[index - 1].block) and (
            x + 1 < grid.width and not grid.squares[index + 1].block)
        starts_down = (y == 0 or grid.squares[index - grid.width].block) and (
            y + 1 < grid.height and not grid.squares[index + grid.width].block)
        if starts_across or starts_down:
            number += 1
            if starts_across:
                across.append((number, index))
            if starts_down:
                down.append((number, index))
    return across, down


def section(name: bytes, data: bytes) -> bytes:
    return name + struct.pack("<HH", len(data), checksum(data)) + data + b"\0"


def to_puz(puzzle: CrosswordPuzzle, game: Game = None, title: str | None = None) -> bytes:
    """Return the puzzle as an Across Lite .puz file."""
    grid = to_grid(puzzle, game, title)
    problems = list(grid.problems)

    across, down = numbering(grid)
    expected = [(n, i) for n, i in across] + [(n, i) for n, i in down]
    actual = [(c.number, c.cells[0]) for c in grid.across] + [(c.number, c.cells[0]) for c in grid.down]
    if not problems and sorted(expected) != sorted(actual):
        problems.append("numbering or entries that don't follow standard crossword rules")
    if grid.width > 255 or grid.height > 255:
        problems.append("a grid larger than 255 squares across")

    solution, fill = bytearray(), bytearray()
    rebus_answers: dict[str, int] = {}
    rebus = bytearray()
    for square in grid.squares:
        if square.block:
            solution += b"."
            fill += b"."
            rebus += b"\0"
            continue
        answer = square.solution.upper() or "X"
        letter = latin1(answer[0], "answers", problems)[:1] or b"X"
        solution += letter
        fill += (latin1(square.fill[:1].upper(), "fill", problems)[:1] or b"-") if square.fill else b"-"
        if len(answer) > 1:
            rebus += bytes([rebus_answers.setdefault(answer, len(rebus_answers)) + 1])
        else:
            rebus += b"\0"

    clues = sorted(
        [(c.number, 0, c.text) for c in grid.across] + [(c.number, 1, c.text) for c in grid.down]
    )
    strings = [latin1(grid.title, "the title", problems), latin1(grid.author, "the byline", problems),
               latin1(grid.copyright, "the copyright", problems)]
    clue_bytes = [latin1(text, "clues", problems) for _, _, text in clues]
    notes = latin1(grid.notes, "the notes", problems)
    if problems:
        raise NYTGamesExportError("puz", list(dict.fromkeys(problems)))

    def text_checksum(value: int) -> int:
        for string in strings:
            if string:
                value = checksum(string + b"\0", value)
        for clue in clue_bytes:
            value = checksum(clue, value)
        if notes:
            value = checksum(notes + b"\0", value)
        return value

    cib = struct.pack("<BBHHH", grid.width, grid.height, len(clue_bytes), 1, 0)
    c_cib = checksum(cib)
    c_solution = checksum(solution)
    c_fill = checksum(fill)
    c_text = text_checksum(0)
    overall = text_checksum(checksum(fill, checksum(solution, c_cib)))
    masked_low = bytes(a ^ (c & 0xFF) for a, c in zip(b"ICHE", (c_cib, c_solution, c_fill, c_text)))
    masked_high = bytes(a ^ (c >> 8) for a, c in zip(b"ATED", (c_cib, c_solution, c_fill, c_text)))

    header = (struct.pack("<H", overall) + b"ACROSS&DOWN\0" + struct.pack("<H", c_cib)
              + masked_low + masked_high + b"1.3\0" + b"\0\0" + b"\0\0" + b"\0" * 12 + cib)
    body = bytes(solution) + bytes(fill)
    body += b"".join(s + b"\0" for s in strings) + b"".join(c + b"\0" for c in clue_bytes) + notes + b"\0"

    extensions = b""
    if rebus_answers:
        table = "".join(f"{n:2d}:{answer};" for answer, n in sorted(rebus_answers.items(), key=lambda a: a[1]))
        extensions += section(b"GRBS", bytes(rebus))
        extensions += section(b"RTBL", latin1(table, "rebus answers", problems))
    flags = bytes((0x80 if s.circled or s.shaded else 0) | (0x40 if s.revealed else 0)
                  for s in grid.squares)
    if any(flags):
        extensions += section(b"GEXT", flags)
    if grid.seconds is not None:
        extensions += section(b"LTIM", f"{grid.seconds},1".encode())
    return header + body + extensions


# Crossword Compiler XML

XML_NAMESPACE = "http://crossword.info/xml/rectangular-puzzle"


def to_xml(puzzle: CrosswordPuzzle, game: Game = None, title: str | None = None) -> str:
    """Return the puzzle as Crossword Compiler rectangular-puzzle XML."""
    grid = to_grid(puzzle, game, title)
    check(grid, "xml")
    ET.register_namespace("", XML_NAMESPACE)

    def tag(name: str) -> str:
        return f"{{{XML_NAMESPACE}}}{name}"

    root = ET.Element(tag("rectangular-puzzle"))
    metadata = ET.SubElement(root, tag("metadata"))
    url = f"urn:nytimes:crossword:{grid.puzzle_id}"
    for name, value in (("title", grid.title), ("created", grid.date.isoformat()),
                        ("creator", grid.author), ("editor", grid.editor), ("rights", ""),
                        ("copyright", grid.copyright), ("publisher", "The New York Times"),
                        ("identifier", url), ("description", grid.notes)):
        ET.SubElement(metadata, tag(name)).text = value

    crossword = ET.SubElement(root, tag("crossword"))
    grid_element = ET.SubElement(crossword, tag("grid"), width=str(grid.width), height=str(grid.height))
    ET.SubElement(grid_element, tag("grid-look"), {
        "numbering-scheme": "normal", "grid-line-color": "#000000", "block-color": "#000000",
        "font-color": "#000000", "number-color": "#000000",
    })
    for index, square in enumerate(grid.squares):
        x, y = grid.xy(index)
        attributes = {"x": str(x + 1), "y": str(y + 1)}
        if square.block:
            attributes["type"] = "block"
        else:
            attributes["solution"] = square.solution
            if square.label is not None:
                attributes["number"] = str(square.label)
            if square.circled:
                attributes["background-shape"] = "circle"
            if square.shaded:
                attributes["background-color"] = f"#{SHADE_COLOR}"
            if square.fill:
                attributes["solve-state"] = square.fill
            if square.revealed:
                attributes["solve-status"] = "revealed"
            elif square.penciled:
                attributes["solve-status"] = "pencil"
        ET.SubElement(grid_element, tag("cell"), attributes)

    words = []
    for clues in (grid.across, grid.down):
        for clue in clues:
            xs = sorted({grid.xy(c)[0] + 1 for c in clue.cells})
            ys = sorted({grid.xy(c)[1] + 1 for c in clue.cells})
            words.append((clue, f"{xs[0]}-{xs[-1]}" if len(xs) > 1 else str(xs[0]),
                          f"{ys[0]}-{ys[-1]}" if len(ys) > 1 else str(ys[0])))
    for word_id, (_, x, y) in enumerate(words, start=1):
        ET.SubElement(crossword, tag("word"), id=str(word_id), x=x, y=y)
    word_id = 1
    for name, clues in (("Across", grid.across), ("Down", grid.down)):
        container = ET.SubElement(crossword, tag("clues"), ordering="normal")
        heading = ET.SubElement(ET.SubElement(container, tag("title")), tag("b"))
        heading.text = name
        for clue in clues:
            element = ET.SubElement(container, tag("clue"), word=str(word_id), number=str(clue.number))
            element.text = clue.text
            word_id += 1
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"

"""nytg puzzle commands.

Answers are hidden unless --answers is given, in every output format.
"""
import enum
from pathlib import Path
from typing import Annotated
from typing import Optional

import typer
from rich.columns import Columns
from rich.table import Table
from rich.text import Text

from nytgames import formats
from nytgames import views
from nytgames.cli.output import FormatOption
from nytgames.cli.output import console
from nytgames.cli.output import emit
from nytgames.cli.output import key_value_table
from nytgames.cli.state import date_arg
from nytgames.cli.state import state
from nytgames.files import write_file

DateArgument = Annotated[
    str,
    typer.Argument(help="YYYY-MM-DD, today, yesterday, tomorrow or a weekday.", show_default=True),
]
AnswersOption = Annotated[bool, typer.Option("--answers", "-a", help="Show the answers.")]

CONNECTIONS_COLORS = ["black on yellow", "black on green", "white on blue", "white on magenta"]


def tiles(word: str, style: str = "bold white on green") -> Text:
    """Render a word as letter tiles."""
    text = Text()
    for letter in word.upper():
        text.append(f" {letter} ", style=style)
        text.append(" ")
    return text


def register(app: typer.Typer) -> None:
    """Add the puzzle commands to the root app."""
    app.command("wordle")(wordle)
    app.command("connections")(connections)
    app.command("strands")(strands)
    app.command("bee")(bee)
    app.command("letter-boxed")(letter_boxed)
    app.command("crossword")(crossword)


def wordle(date: DateArgument = "today", answers: AnswersOption = False, fmt: FormatOption = None) -> None:
    """Show a Wordle puzzle."""
    data = views.wordle_view(state.client().wordle(date_arg(date).isoformat()), answers)

    def table(data):
        yield key_value_table({k: v for k, v in data.items() if k != "solution"},
                              title=f"[bold]Wordle {data['number']}[/bold]")
        if "solution" in data:
            yield Text()
            yield tiles(data["solution"])

    emit(data, fmt, table)


def connections(date: DateArgument = "today", answers: AnswersOption = False, fmt: FormatOption = None) -> None:
    """Show a Connections puzzle: the board, or the groups with --answers."""
    data = views.connections_view(state.client().connections(date_arg(date).isoformat()), answers)
    emit(data, fmt, connections_table)


def connections_table(data):
    yield Text(f"{data.get('title') or 'Connections'} {data['date']}", style="bold")
    if "categories" in data:
        grid = Table(show_header=False, box=None, padding=(0, 1))
        for color, category in zip(CONNECTIONS_COLORS, data["categories"]):
            grid.add_row(Text(f" {category['title']} ", style=color),
                         ", ".join(category["cards"]))
    else:
        grid = Table(show_header=False, show_lines=True)
        for row in data["board"]:
            grid.add_row(*row)
    yield grid


def strands(date: DateArgument = "today", answers: AnswersOption = False, fmt: FormatOption = None) -> None:
    """Show a Strands puzzle: the theme and board, and the words with --answers."""
    data = views.strands_view(state.client().strands(date_arg(date).isoformat()), answers)
    emit(data, fmt, strands_table)


def strands_table(data):
    styles = {}
    word_styles = [f"bold white on {color}" for color in
                   ("blue", "dark_cyan", "purple4", "dark_green", "deep_pink4", "dark_red")]
    for coords in data.get("theme_coords", {}).values():
        # Give each word a color that none of its neighboring letters have.
        neighbors = {styles.get((r + dr, c + dc)) for r, c in coords
                     for dr in (-1, 0, 1) for dc in (-1, 0, 1)}
        style = next((s for s in word_styles if s not in neighbors), word_styles[0])
        styles.update({tuple(c): style for c in coords})
    styles.update({tuple(c): "bold black on yellow" for c in data.get("spangram_coords", [])})
    yield Text(f"{data.get('title') or 'Strands'} {data['date']}: {data['clue']}", style="bold")
    board = Text()
    for r, row in enumerate(data["board"]):
        for c, letter in enumerate(row):
            board.append(f" {letter} ", style=styles.get((r, c), ""))
        board.append("\n")
    yield board
    if "spangram" in data:
        yield Text.assemble(("Spangram: ", "bold"), (data["spangram"], "yellow"))
        yield Text.assemble(("Theme words: ", "bold"), ", ".join(data["theme_words"]))


def bee(
    date: DateArgument = "today",
    answers: AnswersOption = False,
    hints: Annotated[bool, typer.Option("--hints", help="Show Spelling Bee Forum style hints.")] = False,
    fmt: FormatOption = None,
) -> None:
    """Show a Spelling Bee puzzle, with hints or answers."""
    puzzle = state.client().spelling_bee_puzzle(date_arg(date, "spelling-bee").isoformat())
    data = views.bee_view(puzzle, answers, hints)

    def table(data):
        letters = Text()
        letters.append(f" {data['center_letter'].upper()} ", style="bold black on yellow")
        for letter in data["outer_letters"]:
            letters.append(f" {letter.upper()} ", style="bold white on grey35")
        yield Text(f"Spelling Bee {data['date']}", style="bold")
        yield letters
        yield Text(f"{data['words']} words, {data['points']} points, {data['pangrams']} pangrams"
                   + (", perfect pangram" if data.get("hints", {}).get("perfect") else ""))
        if "hints" in data:
            counts = data["hints"]["counts"]
            grid = Table(header_style="bold", title="Words by first letter and length", title_justify="left")
            grid.add_column("")
            for length in counts["lengths"]:
                grid.add_column(str(length), justify="right")
            grid.add_column("Σ", justify="right", style="bold")
            for letter, row in counts["letters"].items():
                grid.add_row(letter.upper(), *(str(n or "-") for n in row))
            grid.add_row("Σ", *(str(n) for n in counts["totals"]), style="bold")
            yield grid
            yield Text("Two letter list: " + "  ".join(
                f"{pair.upper()}-{n}" for pair, n in data["hints"]["pairs"].items()))
        if "answers" in data:
            pangrams = set(data["pangram_words"])
            yield Columns(
                [Text(w, style="bold yellow" if w in pangrams else "") for w in sorted(data["answers"])],
                padding=(0, 2),
            )

    emit(data, fmt, table)


def letter_boxed(date: DateArgument = "today", answers: AnswersOption = False, fmt: FormatOption = None) -> None:
    """Show a Letter Boxed puzzle."""
    data = views.letter_boxed_view(state.client().letter_boxed(date_arg(date, "letter-boxed").isoformat()), answers)

    def table(data):
        top, right, bottom, left = (list(side) for side in data["sides"])
        box = Text()
        box.append("     " + "   ".join(top) + "\n", style="bold")
        box.append("   ┌" + "─" * 11 + "┐\n")
        for l_letter, r_letter in zip(left, right):
            box.append(f" {l_letter} ", style="bold")
            box.append("│" + " " * 11 + "│")
            box.append(f" {r_letter}\n", style="bold")
        box.append("   └" + "─" * 11 + "┘\n")
        box.append("     " + "   ".join(bottom), style="bold")
        yield Text(f"Letter Boxed {data['date']}: solve in {data['par']} words", style="bold")
        yield box
        if "solution" in data:
            yield Text.assemble(("NYT's solution: ", "bold"), " → ".join(data["solution"]))
            yield Text(f"{len(data['dictionary'])} accepted words", style="dim")

    emit(data, fmt, table)


def save_crossword(client, puzzle, kind: str, path: Path, progress: bool) -> None:
    """Save a crossword in the format matching the file extension."""
    fmt = path.suffix.lower().lstrip(".")
    if fmt not in formats.FORMATS:
        raise typer.BadParameter(f"Use a .puz, .ipuz or .xml file name, not {path.name!r}.",
                                 param_hint="'--save'")
    game = client.crossword_game(puzzle.id, kind) if progress else None
    try:
        data = formats.export(puzzle, fmt, game, title=views.export_title(puzzle, kind))
    except formats.NYTGamesExportError as err:
        console.print(f"[red]Can't save this puzzle as .{fmt}:[/red] " + "; ".join(err.reasons))
        raise typer.Exit(1) from None
    write_file(path, data, overwrite=True)
    console.print(f"Saved [bold]{path}[/bold]" + (" with your progress" if progress else ""))
    for note in formats.fidelity(puzzle, fmt, game):
        console.print(f"[dim]Note: {note}[/dim]")


class CrosswordType(str, enum.Enum):
    daily = "daily"
    mini = "mini"
    midi = "midi"
    bonus = "bonus"


def crossword(
    publish_type: Annotated[CrosswordType, typer.Argument(help="daily, mini, midi or bonus.")] = CrosswordType.daily,
    date: DateArgument = "today",
    answers: AnswersOption = False,
    clues: Annotated[bool, typer.Option(help="Show the clues.")] = True,
    save: Annotated[
        Optional[Path],
        typer.Option("--save", "-o", help="Save as a crossword file: .puz, .ipuz or .xml (Crossword Compiler).",
                     dir_okay=False),
    ] = None,
    progress: Annotated[bool, typer.Option("--progress", help="Include your saved progress in --save.")] = False,
    puzzle_id: Annotated[
        Optional[int],
        typer.Option("--id", help="Show the crossword with this puzzle ID instead, e.g. for dates with two."),
    ] = None,
    fmt: FormatOption = None,
) -> None:
    """Show a crossword: the grid and clues, filled in with --answers.

    With --save, write it to a file for other crossword apps instead.
    """
    kind = publish_type.value
    day = date_arg(date, f"crossword-{kind}")
    client = state.client()
    if puzzle_id is not None:
        puzzle = client.crossword_by_id(puzzle_id)
    else:
        puzzle = client.crossword(kind, None if date == "today" and kind != "bonus" else day.isoformat())
    if save:
        return save_crossword(client, puzzle, kind, save, progress)
    body = puzzle.body[0]
    width = body.dimensions["width"]
    cells = body.cells
    data = views.crossword_view(puzzle, kind, answers, clues)

    def table(data):
        heading = f"{kind.title()} crossword {data['date']}"
        if data.get("title"):
            heading += f": {data['title']}"
        yield Text(heading, style="bold")
        yield Text(f"By {', '.join(data['constructors'])}"
                   + (f" · Edited by {data['editor']}" if data.get("editor") else ""), style="dim")
        board = Text()
        for r, row in enumerate(data["grid"]):
            for c in range(width):
                cell = cells[r * width + c]
                if not cell.type:
                    board.append("███", style="grey30")
                elif answers:
                    board.append(f" {(cell.answer or ' ')[0]} ", style="bold black on white")
                else:
                    label = str(cell.label or "")
                    board.append(f"{label:<3}", style="black on white")
            board.append("\n")
        yield board
        if "clues" in data:
            panels = []
            for name, entries in data["clues"].items():
                t = Table(title=name.title(), title_justify="left", show_header=False, box=None)
                t.add_column(justify="right", style="bold")
                t.add_column(max_width=48)
                if answers:
                    t.add_column(style="green")
                for entry in entries:
                    t.add_row(entry["label"], entry["clue"], *([entry["answer"]] if answers else []))
                panels.append(t)
            yield Columns(panels, padding=(0, 4))

    emit(data, fmt, table)

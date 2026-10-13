"""nytg archive: save puzzles as JSON files, one per date."""
import datetime
import enum
import functools
import hashlib
import json
import time
from pathlib import Path
from typing import Annotated
from typing import Optional

import typer
from rich.progress import BarColumn
from rich.progress import MofNCompleteColumn
from rich.progress import Progress
from rich.progress import TextColumn
from rich.progress import TimeRemainingColumn

from nytgames import NYTGamesAuthenticationError
from nytgames import NYTGamesClient
from nytgames import NYTGamesHTTPError
from nytgames import NYTGamesNotFoundError
from nytgames import __version__
from nytgames import formats
from nytgames.cli import dates
from nytgames.cli.dates import date_range
from nytgames.cli.output import FormatOption
from nytgames.cli.output import emit
from nytgames.cli.output import err_console
from nytgames.cli.output import key_value_table
from nytgames.cli.state import date_arg
from nytgames.cli.state import state
from nytgames.files import write_file


class ArchiveGame(str, enum.Enum):
    wordle = "wordle"
    connections = "connections"
    strands = "strands"
    spelling_bee = "spelling-bee"
    letter_boxed = "letter-boxed"
    crossword_daily = "crossword-daily"
    crossword_mini = "crossword-mini"
    crossword_midi = "crossword-midi"


def archive_items(client: NYTGamesClient, game: ArchiveGame, days: list) -> tuple[list, list]:
    """Return the (date, file stem, fetch) items to archive, and dates known to have no puzzle.

    Most games have one puzzle per date, fetched by date. Crosswords are listed
    from the games archive and fetched by ID, because a few dates have two
    (special puzzles alongside a daily); those are saved as
    YYYY-MM-DD-ID files. Future dates, which the archive doesn't list yet,
    are fetched by date.
    """
    if not game.value.startswith("crossword-"):
        fetch = {
            ArchiveGame.wordle: client.wordle,
            ArchiveGame.connections: client.connections,
            ArchiveGame.strands: client.strands,
            ArchiveGame.spelling_bee: client.spelling_bee_puzzle,
            ArchiveGame.letter_boxed: client.letter_boxed,
        }[game]
        return [(d.isoformat(), d.isoformat(), functools.partial(fetch, d.isoformat())) for d in days], []

    kind = game.value.split("-", 1)[1]
    today = dates.today()
    listed_days = [d for d in days if d <= today]
    by_date: dict[str, list] = {}
    if listed_days:
        for puzzle in client.archive(f"crossword_{kind}", listed_days[0].isoformat(), listed_days[-1].isoformat()):
            by_date.setdefault(puzzle.print_date, []).append(puzzle.id)
    items, missing = [], []
    for d in days:
        iso = d.isoformat()
        if d > today:
            items.append((iso, iso, functools.partial(client.crossword, kind, iso)))
        elif iso not in by_date:
            missing.append(iso)
        else:
            ids = by_date[iso]
            for puzzle_id in ids:
                stem = iso if len(ids) == 1 else f"{iso}-{puzzle_id}"
                items.append((iso, stem, functools.partial(client.crossword_by_id, puzzle_id)))
    return items, missing


def archive(
    game: Annotated[ArchiveGame, typer.Argument(help="The game to archive.")],
    start: Annotated[str, typer.Option("--from", help='First date, or "first" for the first puzzle.')] = "today",
    end: Annotated[str, typer.Option("--to", help="Last date.")] = "today",
    out: Annotated[
        Path, typer.Option("--out", "-o", help="Directory to save into.", file_okay=False)
    ] = Path("nyt-archive"),
    delay: Annotated[float, typer.Option(help="Seconds to wait between requests.", min=0)] = 0.25,
    overwrite: Annotated[bool, typer.Option(help="Download dates that are already saved.")] = False,
    file_format: Annotated[
        str, typer.Option("--as", help="File format: json, or for crosswords puz, ipuz or xml.")
    ] = "json",
    fmt: FormatOption = None,
) -> None:
    """Save each date's puzzle in OUT/GAME/YYYY-MM-DD.json (or .puz, .ipuz, .xml).

    Dates already saved are skipped, so an interrupted archive can be resumed
    by running the same command again. Dates without a puzzle are reported as
    missing, and crosswords that can't be saved in the --as format (some
    special puzzles) as unsupported.

    OUT/GAME/manifest.json records when each file was fetched, NYT's own
    update time, the nytimes-games version and a SHA-256 hash. With
    --overwrite, a puzzle NYT has changed since it was saved keeps its
    previous version in OUT/GAME/revisions/ and is listed as updated.
    """
    if file_format != "json" and (file_format not in formats.FORMATS or not game.value.startswith("crossword-")):
        raise typer.BadParameter("Use json, or puz, ipuz or xml for crosswords.", param_hint="'--as'")
    first = date_arg(start, game.value)
    last = date_arg(end, game.value)
    if first > last:
        raise typer.BadParameter("--from is after --to")
    directory = out / game.value
    directory.mkdir(parents=True, exist_ok=True)
    days = list(date_range(first, last))
    items, missing = archive_items(state.client(), game, days)
    result: dict[str, Optional[object]] = {"game": game.value, "directory": str(directory),
                                           "format": file_format, "saved": 0, "skipped": 0,
                                           "updated": [], "missing": missing, "unsupported": [],
                                           "errors": []}
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"files": {}}
    columns = (TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), TimeRemainingColumn())
    try:
        archive_days(items, directory, file_format, overwrite, delay, manifest, result,
                     Progress(*columns, console=err_console, transient=True), game)
    finally:
        # Atomic, so an interrupted run leaves the previous complete manifest.
        write_file(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(), overwrite=True)

    def table(data):
        yield key_value_table({
            "Saved": data["saved"],
            "Already saved": data["skipped"],
            "Changed by NYT": ", ".join(data["updated"]) if len(data["updated"]) <= 5
            else f"{len(data['updated'])} dates",
            "No puzzle": ", ".join(data["missing"]) if len(data["missing"]) <= 5
            else f"{len(data['missing'])} dates",
            "Can't save as " + data["format"]: len(data["unsupported"]),
            "Errors": len(data["errors"]),
            "Directory": data["directory"],
        }, title=f"[bold]Archived {data['game']}[/bold]")

    emit(result, fmt, table)
    if result["errors"]:
        raise typer.Exit(1)


def archive_days(items, directory: Path, file_format: str, overwrite: bool, delay: float,
                 manifest: dict, result: dict, progress_bar: Progress, game: ArchiveGame) -> None:
    """Fetch and save each item, updating the manifest and result."""
    with progress_bar as progress:
        task = progress.add_task(f"Archiving {game.value}", total=len(items))
        for day, stem, fetch in items:
            path = directory / f"{stem}.{file_format}"
            if path.exists() and not overwrite:
                # A file without a manifest entry, such as one saved by a run
                # interrupted before its manifest was, is recorded as it is.
                if path.name not in manifest["files"]:
                    manifest["files"][path.name] = {"date": day, "retrieved_at": None,
                                                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                result["skipped"] += 1
                progress.advance(task)
                continue
            try:
                puzzle = fetch()
            except NYTGamesAuthenticationError:
                raise
            except NYTGamesNotFoundError:
                result["missing"].append(day)
            except NYTGamesHTTPError as err:
                result["errors"].append({"date": day, "error": str(err)})
            else:
                if file_format == "json":
                    content = (json.dumps(puzzle.model_dump(mode="json", by_alias=True),
                                          ensure_ascii=False, indent=2) + "\n").encode()
                else:
                    try:
                        content = formats.export(puzzle, file_format)
                    except formats.NYTGamesExportError as err:
                        result["unsupported"].append({"date": stem, "reasons": err.reasons})
                        content = None
                if content is not None:
                    save(path, content, day, puzzle, manifest, result)
            progress.advance(task)
            if delay:
                time.sleep(delay)


def save(path: Path, content: bytes, day: str, puzzle, manifest: dict, result: dict) -> None:
    """Write a file atomically and record it in the manifest.

    If NYT has changed a puzzle since it was saved, the previous file is
    copied to revisions/ first. The file is only replaced once the new
    content is completely written, so a failed write leaves it as it was.
    """
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    digest = hashlib.sha256(content).hexdigest()
    previous = manifest["files"].get(path.name)
    revisions = previous.get("revisions", []) if previous else []
    if path.exists():
        old_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if old_digest != digest:
            fetched = ((previous or {}).get("retrieved_at") or "unknown").replace(":", "")
            revision = path.parent / "revisions" / f"{path.stem}.{fetched}{path.suffix}"
            write_file(revision, path.read_bytes(), overwrite=True)
            revisions.append({"file": f"revisions/{revision.name}", "sha256": old_digest,
                              "retrieved_at": (previous or {}).get("retrieved_at")})
            result["updated"].append(day)
    write_file(path, content, overwrite=True)
    manifest["files"][path.name] = {
        "date": day,
        "puzzle_id": getattr(puzzle, "id", None),
        "retrieved_at": now,
        "nyt_updated": getattr(puzzle, "lastUpdated", None),
        "sha256": digest,
        "nytimes_games": __version__,
        **({"revisions": revisions} if revisions else {}),
    }
    result["saved"] += 1

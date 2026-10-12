"""nytg commands about the user: stats, today and history. These need cookies."""
import datetime
import enum
from collections.abc import Iterable
from typing import Annotated
from typing import Optional

import typer
from rich.progress import Progress
from rich.table import Table
from rich.text import Text

from nytgames import views
from nytgames.cli import dates
from nytgames.cli.dates import format_seconds
from nytgames.cli.output import FormatOption
from nytgames.cli.output import emit
from nytgames.cli.output import err_console
from nytgames.cli.output import key_value_table
from nytgames.cli.state import date_arg
from nytgames.cli.state import state
from nytgames.views import percent

FromOption = Annotated[
    Optional[str], typer.Option("--from", help='First date, or "first" (default: 30 days ago).')
]
ToOption = Annotated[Optional[str], typer.Option("--to", help="Last date (default: today).")]


def register(app: typer.Typer) -> None:
    """Add the player commands to the root app."""
    app.command("stats")(stats)
    app.command("today")(today)
    app.command("wordlebot")(wordlebot)
    app.command("badges")(badges)
    history = typer.Typer(help="Your results for a range of dates.", no_args_is_help=True)
    history.command("crossword")(history_crossword)
    history.command("wordle")(history_wordle)
    history.command("connections")(history_connections)
    history.command("strands")(history_strands)
    history.command("bee")(history_bee)
    history.command("bonus")(history_bonus)
    app.add_typer(history, name="history")


def bar(value: int, maximum: int, width: int = 30) -> str:
    return "█" * max(1 if value else 0, round(width * value / maximum)) if maximum else ""


class Game(str, enum.Enum):
    all = "all"
    wordle = "wordle"
    connections = "connections"
    strands = "strands"
    bee = "bee"
    crossword = "crossword"


def stats(
    game: Annotated[Game, typer.Argument(help="A game for more detail, or all for a summary.")] = Game.all,
    fmt: FormatOption = None,
) -> None:
    """Show your stats. Spelling Bee counts Queen Bees as wins."""
    player = state.client().player_stats()
    s = player.stats
    if game == Game.all:
        data = views.summary_rows(s)

        def table(data):
            t = Table(title=f"NYT Games stats for user {player.user_id}", title_justify="left",
                      header_style="bold")
            for column, justify in (("Game", "left"), ("Played", "right"), ("Won", "right"),
                                    ("Win %", "right"), ("Streak", "right"), ("Max streak", "right")):
                t.add_column(column, justify=justify)
            for row in data:
                t.add_row(row["game"], str(row["played"]), str(row["won"]),
                          "" if row["win_rate"] is None else f"{row['win_rate']:g}",
                          "" if row["current_streak"] is None else str(row["current_streak"]),
                          "" if row["max_streak"] is None else str(row["max_streak"]))
            yield t

        return emit(data, fmt, table)

    model = {
        Game.wordle: s.wordle, Game.connections: s.connections, Game.strands: s.strands,
        Game.bee: s.spelling_bee, Game.crossword: s.crossword_daily,
    }[game]
    if model is None:
        err_console.print(f"No {game.value} stats yet.")
        raise typer.Exit(1)
    data = model.model_dump(mode="json", by_alias=True)
    if game == Game.crossword:
        data = {"daily": data,
                "mini": s.crossword_mini.model_dump(mode="json") if s.crossword_mini else None,
                "midi": s.crossword_midi.model_dump(mode="json") if s.crossword_midi else None}
    emit(data, fmt, {
        Game.wordle: wordle_table, Game.connections: connections_table,
        Game.strands: strands_table, Game.bee: bee_table, Game.crossword: crossword_table,
    }[game])


def distribution(title: str, counts: dict[str, int], highlight: str | None = None) -> Table:
    t = Table(title=title, title_justify="left", show_header=False, box=None)
    t.add_column(justify="right", style="bold")
    t.add_column()
    t.add_column(justify="right")
    top = max(counts.values(), default=0)
    for label, n in counts.items():
        t.add_row(label, Text(bar(n, top), style="red" if label == highlight else "green"), str(n))
    return t


def wordle_table(data):
    total = data.get("totalStats") or {}
    calc = data.get("calculatedStats") or {}
    yield key_value_table({
        "Played": total.get("gamesPlayed"), "Won": total.get("gamesWon"),
        "Win %": percent(total.get("gamesWon"), total.get("gamesPlayed")),
        "Current streak": calc.get("currentStreak"), "Max streak": calc.get("maxStreak"),
        "Last won": calc.get("lastWonPrintDate"),
    }, title="[bold]Wordle[/bold]")
    guesses = total.get("guesses") or {}
    yield distribution("Guess distribution", {k: guesses.get(k, 0) for k in ("1", "2", "3", "4", "5", "6", "fail")},
                       highlight="fail")


def connections_table(data):
    yield key_value_table({
        "Completed": data["puzzles_completed"], "Won": data["puzzles_won"],
        "Win %": percent(data["puzzles_won"], data["puzzles_completed"]),
        "Current streak": data["current_streak"], "Max streak": data["max_streak"],
    }, title="[bold]Connections[/bold]")
    yield distribution("Mistakes", {k: data["mistakes"].get(k, 0) for k in sorted(data["mistakes"])})


def strands_table(data):
    yield key_value_table({
        "Started": data["puzzles_started"], "Completed": data["puzzles_completed"],
        "Current streak": data["current_streak"], "Max streak": data["max_streak"],
        "Spangram first": data["spangram_first"], "No hints": data["no_hints"],
    }, title="[bold]Strands[/bold]")


def bee_table(data):
    longest = data.get("longest_word") or {}
    yield key_value_table({
        "Puzzles started": data["puzzles_started"], "Words found": data["total_words"],
        "Pangrams": data["total_pangrams"],
        "Longest word": f"{longest.get('word', '')} ({longest.get('print_date', '')})" if longest else None,
    }, title="[bold]Spelling Bee[/bold]")
    order = ["Beginner", "Good Start", "Moving Up", "Good", "Solid", "Nice", "Great", "Amazing",
             "Genius", "Queen Bee"]
    ranks = data.get("ranks") or {}
    yield distribution("Best rank reached", {r: ranks.get(r, 0) for r in order})


def crossword_table(data):
    daily = data["daily"]
    streak = daily.get("dailyStreaks") or {}
    yield key_value_table({
        "Started": daily["puzzlesStarted"], "Solved": daily["puzzlesSolved"],
        "Solve rate": f"{100 * daily['solveRate']:.1f}%",
        "Current streak": streak.get("current"), "Longest streak": streak.get("longest"),
    }, title="[bold]Daily crossword[/bold]")
    t = Table(header_style="bold")
    for column in ("Day", "Solves", "Average", "Best", "Best date", "This week", "Day streak"):
        t.add_column(column, justify="left" if column in ("Day", "Best date") else "right")
    for day, s in daily["dailyStats"].items():
        best = s.get("best") or {}
        t.add_row(day.title(), str(s["totalSolves"]), format_seconds(s["avgTimeSeconds"]),
                  format_seconds(best.get("timeSeconds")), best.get("date") or "",
                  format_seconds(s.get("thisWeeksTime")) if s.get("thisWeeksTime") else "",
                  str((s.get("verticalStreak") or {}).get("current", "")))
    yield t
    for name in ("mini", "midi"):
        s = data.get(name)
        if s:
            streaks = s.get("streaks") or {}
            yield key_value_table({
                "Solved": f"{s['puzzlesSolved']} of {s['puzzlesStarted']}",
                "Average": format_seconds(s["avgTimeSeconds"]),
                "Best": f"{format_seconds(s.get('bestTimeSeconds'))} ({s.get('bestDate')})",
                "Streak": f"{streaks.get('current')} (longest {streaks.get('longest')})",
            }, title=f"[bold]{name.title()}[/bold]")


def today(fmt: FormatOption = None) -> None:
    """Show which of today's games you've played."""
    day = dates.today().isoformat()
    rows = views.today_rows(state.client(), dates.today())

    def table(data):
        done = {"win", "solved", "played", "queen bee", "genius"}
        t = Table(title=f"Today's games ({day})", title_justify="left", header_style="bold")
        t.add_column("")
        t.add_column("Game")
        t.add_column("Status")
        t.add_column("Detail")
        for row in data:
            status = row["status"].lower()
            icon = ("[green]✔[/green]" if status in done else "[red]✘[/red]" if status == "fail"
                    else "[dim]·[/dim]" if status == "not played" else "[yellow]…[/yellow]")
            t.add_row(icon, row["game"], row["status"], row["detail"])
        yield t

    emit(rows, fmt, table)


def date_window(start: str | None, end: str | None, game: str) -> tuple[datetime.date, datetime.date]:
    last = date_arg(end, game) if end else dates.today()
    first = date_arg(start, game) if start else last - datetime.timedelta(days=29)
    if first > last:
        raise typer.BadParameter("--from is after --to")
    return first, last


def progress(items: Iterable, total: int, description: str):
    """Show a progress bar on stderr for long runs."""
    if total <= 7:
        yield from items
        return
    with Progress(console=err_console, transient=True) as bar_:
        task = bar_.add_task(description, total=total)
        for item in items:
            yield item
            bar_.advance(task)


class CrosswordKind(str, enum.Enum):
    daily = "daily"
    mini = "mini"
    midi = "midi"
    bonus = "bonus"


def history_crossword(
    publish_type: Annotated[CrosswordKind, typer.Argument(help="daily, mini, midi or bonus.")] = CrosswordKind.daily,
    start: FromOption = None,
    end: ToOption = None,
    fmt: FormatOption = None,
) -> None:
    """Your crossword results: solved, solve time, gold star and help used."""
    kind = publish_type.value
    first, last = date_window(start, end, f"crossword-{kind}")
    rows = views.crossword_results(state.client(), kind, first, last, progress)

    def table(data):
        t = Table(title=f"{kind.title()} crosswords {first} to {last}", title_justify="left",
                  header_style="bold")
        for column in ("Date", "Day", "Author", "Solved", "Time", ""):
            t.add_column(column, justify="right" if column == "Time" else "left")
        for row in data:
            solved = ("[green]✔[/green]" if row["solved"]
                      else f"{row['percent_filled']}%" if row["percent_filled"] else "")
            t.add_row(row["date"], row["weekday"][:3], row["author"], solved,
                      format_seconds(row["seconds"]) if row["seconds"] else "",
                      "⭐" if (row["star"] or "").lower() == "gold" else "")
        yield t
        times = [r["seconds"] for r in data if r["solved"] and r["seconds"]]
        if times:
            yield Text(f"{len(times)} solved, average {format_seconds(sum(times) // len(times))},"
                       f" fastest {format_seconds(min(times))}", style="dim")

    emit(rows, fmt, table)


def history_wordle(start: FromOption = None, end: ToOption = None, fmt: FormatOption = None) -> None:
    """Your Wordle results: won or lost, and guesses."""
    first, last = date_window(start, end, "wordle")
    rows = views.wordle_results(state.client(), first, last)

    def table(data):
        t = Table(title=f"Wordle {first} to {last}", title_justify="left", header_style="bold")
        for column in ("Date", "Result", "Guesses", "Words"):
            t.add_column(column)
        for row in data:
            style = {"win": "green", "fail": "red"}.get(row["status"], "dim")
            t.add_row(row["date"], Text(row["status"], style=style), str(row["guesses"] or ""),
                      " ".join(row["board"]).upper())
        yield t

    emit(rows, fmt, table)


def history_connections(start: FromOption = None, end: ToOption = None, fmt: FormatOption = None) -> None:
    """Your Connections results: won or lost, and mistakes."""
    first, last = date_window(start, end, "connections")
    rows = views.connections_results(state.client(), first, last)

    def table(data):
        t = Table(title=f"Connections {first} to {last}", title_justify="left", header_style="bold")
        for column in ("Date", "Result", "Mistakes", "Groups", ""):
            t.add_column(column)
        for row in data:
            style = {"won": "green", "lost": "red"}.get(row["status"], "dim")
            played = row["status"] != "not played"
            t.add_row(row["date"], Text(row["status"], style=style),
                      str(row["mistakes"]) if played and row["mistakes"] is not None else "",
                      f"{row['categories_solved']}/4" if played else "",
                      Text("archive", style="dim") if row["archive"] else "")
        yield t

    emit(rows, fmt, table)


def history_strands(start: FromOption = None, end: ToOption = None, fmt: FormatOption = None) -> None:
    """Your Strands results: solved, and other words found."""
    first, last = date_window(start, end, "strands")
    rows = views.strands_results(state.client(), first, last)

    def table(data):
        t = Table(title=f"Strands {first} to {last}", title_justify="left", header_style="bold")
        for column in ("Date", "Result", "Other words", ""):
            t.add_column(column)
        for row in data:
            style = {"solved": "green"}.get(row["status"], "dim")
            t.add_row(row["date"], Text(row["status"], style=style),
                      str(row["other_words"]) if row["status"] != "not played" else "",
                      Text("archive", style="dim") if row["archive"] else "")
        yield t

    emit(rows, fmt, table)


def history_bee(start: FromOption = None, end: ToOption = None, fmt: FormatOption = None) -> None:
    """Your Spelling Bee results: rank and words found."""
    first, last = date_window(start, end, "spelling-bee")
    rows = views.bee_results(state.client(), first, last, progress)

    def table(data):
        t = Table(title=f"Spelling Bee {first} to {last}", title_justify="left", header_style="bold")
        for column in ("Date", "Rank", "Words", "Pangrams"):
            t.add_column(column)
        for row in data:
            t.add_row(row["date"], Text(row["rank"], style="bold yellow" if row["rank"] == "Queen Bee" else ""),
                      f"{row['words']}/{row['total_words']}", f"{row['pangrams']}/{row['total_pangrams']}")
        yield t

    emit(rows, fmt, table)


def history_bonus(start: FromOption = None, end: ToOption = None, fmt: FormatOption = None) -> None:
    """Your results for the weekly Bonus Puzzles in a date range."""
    first, last = date_window(start, end, "bonus")
    rows = views.bonus_results(state.client(), first, last)

    def table(data):
        t = Table(title=f"Bonus Puzzles {first} to {last}", title_justify="left", header_style="bold")
        for column in ("Week", "Puzzle", "Status", "Detail"):
            t.add_column(column)
        for row in data:
            t.add_row(row["week"], row["title"], row["status"], row["detail"])
        yield t

    emit(rows, fmt, table)


def wordlebot(
    date: Annotated[str, typer.Argument(help="YYYY-MM-DD, today, yesterday or a weekday.")] = "today",
    answers: Annotated[bool, typer.Option("--answers", "-a", help="Show the bot's solve paths.")] = False,
    fmt: FormatOption = None,
) -> None:
    """WordleBot: your luck and skill today, and how everyone did on any day.

    Your own analysis needs cookies and is only available for today's game,
    after you've opened WordleBot.
    """
    client = state.client()
    day = date_arg(date, "wordle")
    puzzle = client.wordle(day.isoformat())
    summary = client.wordlebot_summary(day.isoformat(), solution=puzzle.solution)

    mine = client.wordlebot() if day == dates.today() and state.resolve_cookies()[0] else None
    data = views.wordlebot_view(day, puzzle, summary, mine, answers)

    def table(data):
        everyone, you = data["everyone"], data.get("you")
        t = Table(title=f"WordleBot: Wordle {data['number']} ({data['date']}), {data['mode']} mode",
                  title_justify="left", header_style="bold")
        t.add_column("")
        if you:
            t.add_column("You", justify="right")
        t.add_column("Everyone", justify="right")

        def score(value):
            return "" if value is None else f"{100 * value:.0f}"

        rows = [("Skill", score(you["skill"]) if you else None, score(everyone["skill"])),
                ("Luck", score(you["luck"]) if you else None, score(everyone["luck"])),
                ("Guesses", str(len(you["guesses"])) if you else None,
                 f"{everyone['average_guesses']:.2f}" if everyone["average_guesses"] else "")]
        for label, mine_value, all_value in rows:
            t.add_row(label, *([mine_value] if you else []), all_value)
        yield t
        details = []
        if everyone["players"]:
            details.append(f"{everyone['players']:,} players")
        if everyone["solved_in_three_or_fewer"] is not None:
            details.append(f"{100 * everyone['solved_in_three_or_fewer']:.0f}% solved in 3 or fewer")
        if you and you["skill_percentile_range"]:
            details.append(views.describe_rank(you["skill_percentile_range"]))
        if details:
            yield Text(", ".join(details), style="dim")
        if you:
            rounds = Table(title="By round", title_justify="left", header_style="bold")
            for column in ("Round", "Guess", "Skill", "Luck"):
                rounds.add_column(column, justify="left" if column == "Guess" else "right")
            for i, guess in enumerate(you["guesses"]):
                rounds.add_row(str(i + 1), guess.upper(),
                               score(you["skill_by_round"][i]) if i < len(you["skill_by_round"]) else "",
                               score(you["luck_by_round"][i]) if i < len(you["luck_by_round"]) else "")
            yield rounds
        elif data["date"] == dates.today().isoformat():
            yield Text("Your own analysis appears after you play and open WordleBot "
                       "(and needs your cookies).", style="dim")
        if "bot_paths" in data:
            for strategy, path in data["bot_paths"].items():
                yield Text.assemble((f"{strategy}: ", "bold"), " → ".join(w.upper() for w in path))

    emit(data, fmt, table)


class BadgeGame(str, enum.Enum):
    all = "all"
    wordle = "wordle"
    connections = "connections"
    strands = "strands"
    bee = "bee"


BADGE_GAMES = {BadgeGame.wordle: "wordleV2", BadgeGame.connections: "connections",
               BadgeGame.strands: "strands", BadgeGame.bee: "spelling_bee"}


def badges(
    game: Annotated[BadgeGame, typer.Argument(help="A game, or all.")] = BadgeGame.all,
    earned: Annotated[bool, typer.Option("--earned", help="Only show badges you've earned.")] = False,
    fmt: FormatOption = None,
) -> None:
    """Show your badges, earned or not, with your progress."""
    games = list(BADGE_GAMES.values()) if game == BadgeGame.all else [BADGE_GAMES[game]]
    rows = views.badge_rows(state.client().badges(games))
    if earned:
        rows = [row for row in rows if row["earned"]]

    def table(data):
        t = Table(title="Your NYT Games badges", title_justify="left", header_style="bold")
        t.add_column("")
        t.add_column("Game")
        t.add_column("Badge")
        t.add_column("Progress", justify="right")
        t.add_column("Next", justify="right")
        t.add_column("Earned")
        for row in data:
            t.add_row("[green]✔[/green]" if row["earned"] else "[dim]·[/dim]", row["game"], row["name"],
                      "" if row["progress"] is None else str(row["progress"]),
                      "" if row["next_level"] is None else str(row["next_level"]),
                      row["last_earned"] or "")
        yield t

    emit(rows, fmt, table)

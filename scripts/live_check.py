"""Check every NYT game against the live NYT APIs.

Runs nightly in GitHub Actions (.github/workflows/live.yml) so we find out
when NYT changes an endpoint before users do. Uses no cookies, unless
NYT_COOKIES is set, which adds a check of the user endpoints.

    pip install -e ".[test]"
    python scripts/live_check.py [--json results.json] [--badge badge.json] [--summary summary.md]

Exits 1 if any check fails.
"""
import argparse
import datetime
import json
import os
import sys
import time
import traceback
import zoneinfo
from collections.abc import Callable

import ipuz
import puz

import nytgames
from nytgames import NYTGamesClient
from nytgames import formats
from nytgames import spelling_bee_hints
from nytgames import views
from nytgames.client import BADGE_GAMES

NYT_TIMEZONE = zoneinfo.ZoneInfo("America/New_York")


def checks(client: NYTGamesClient, today: datetime.date) -> list[tuple[str, Callable[[], str]]]:
    """Return (name, check) pairs. Each check returns a short detail or raises."""
    day = today.isoformat()
    week_ago = (today - datetime.timedelta(days=6)).isoformat()
    first_of_month = today.replace(day=1).isoformat()

    def crossword(kind: str, date: str | None = None) -> str:
        puzzle = client.crossword(kind, date)
        body = puzzle.body[0]
        assert body.cells and body.clues, "no cells or clues"
        return f"#{puzzle.id} {body.dimensions['width']}x{body.dimensions['height']}, {len(body.clues)} clues"

    def crossword_by_id(puzzle_id: int) -> str:
        puzzle = client.crossword_by_id(puzzle_id)
        assert puzzle.id == puzzle_id and puzzle.body[0].cells
        return f"#{puzzle.id} from {puzzle.publicationDate}"

    def wordle() -> str:
        puzzle = client.wordle(day)
        assert len(puzzle.solution) == 5
        return f"#{puzzle.days_since_launch}"

    def wordlebot_summary() -> str:
        summary = client.wordlebot_summary(day)
        assert summary.average and summary.guesses
        return f"average {summary.average['normal']:.2f} guesses"

    def connections() -> str:
        puzzle = client.connections(day)
        cards = [card for category in puzzle.categories for card in category.cards]
        assert len(puzzle.categories) == 4 and len(cards) == 16 and all(card.text for card in cards)
        return f"#{puzzle.id}"

    def strands() -> str:
        puzzle = client.strands(day)
        assert puzzle.spangram and puzzle.startingBoard
        return f"#{puzzle.id} {puzzle.clue!r}"

    def bee() -> str:
        puzzle = client.spelling_bee_puzzle(day)
        hints = spelling_bee_hints(puzzle)
        assert hints["pangrams"] >= 1 and len(puzzle.validLetters) == 7
        return f"#{puzzle.id}, {hints['words']} words"

    def bee_page() -> str:
        puzzles = client.spelling_bee_puzzles()
        assert len(puzzles) >= 7
        return f"{len(puzzles)} puzzles on the game page"

    def letter_boxed() -> str:
        puzzle = client.letter_boxed(day)
        assert len(puzzle.sides) == 4 and puzzle.dictionary
        return f"#{puzzle.id}, {len(puzzle.dictionary)} words"

    def bonus() -> str:
        week = client.bonus_week(today.isoformat())
        assert week.puzzles, "no bonus puzzles this week"
        kinds = []
        for listing in week.puzzles:
            client.bonus_puzzle(listing)
            kinds.append(listing.variant or listing.game)
        return f"week of {week.drop_date}: {', '.join(kinds)}"

    def oracle() -> str:
        result = client.crossword_oracle("daily").results
        return f"current #{result.current.puzzle_id}, next #{result.next.puzzle_id}"

    def archive() -> str:
        counts = {game: len(client.archive(game, week_ago, day))
                  for game in ("wordle", "connections", "strands", "crossword_daily",
                               "crossword_mini", "crossword_midi")}
        assert all(counts.values()), counts
        # December 2022 has 32 dailies (two on the 31st), over NYT's 31 per request.
        december = client.archive("crossword_daily", "2022-12-01", "2022-12-31")
        assert len(december) == 32 and december[0].print_date == "2022-12-01", len(december)
        return ", ".join(f"{game} {n}" for game, n in counts.items())

    def crossword_list() -> str:
        results = client.crossword_puzzles("mini", date_start=week_ago, date_end=day).results
        assert results
        return f"{len(results)} Minis"

    def exports() -> str:
        puzzle = client.crossword("mini")
        data = formats.to_puz(puzzle)
        assert puz.load(data).tobytes() == data, ".puz checksums"
        ipuz.read(json.dumps(formats.to_ipuz(puzzle)))
        assert formats.to_xml(puzzle).startswith("<?xml")
        return "today's Mini as .puz, .ipuz and .xml"

    return [
        ("Wordle", wordle),
        ("Connections", connections),
        ("Strands", strands),
        ("Spelling Bee", bee),
        ("Spelling Bee page", bee_page),
        ("Letter Boxed", letter_boxed),
        ("WordleBot summary", wordlebot_summary),
        ("Daily crossword", lambda: crossword("daily")),
        ("Mini crossword", lambda: crossword("mini")),
        ("Midi crossword", lambda: crossword("midi")),
        ("Bonus crossword", lambda: crossword("bonus", first_of_month)),
        ("Crossword schedule", oracle),
        ("Bonus Puzzles", bonus),
        ("Crossword by ID", lambda: crossword_by_id(20759)),
        ("Games archive", archive),
        ("Crossword list", crossword_list),
        ("Crossword export", exports),
    ]


def user_checks(client: NYTGamesClient) -> list[tuple[str, Callable[[], str]]]:
    """Checks that need cookies. Details avoid personal data."""
    def stats() -> str:
        player = client.player_stats()
        assert player.user_id and player.stats.wordle
        return "stats for every game"

    def wordlebot() -> str:
        analysis = client.wordlebot()  # None until WordleBot is opened today
        return "today's analysis" if analysis else "no analysis yet today"

    def badges() -> str:
        case = client.badges()
        assert set(case.trophies) == set(BADGE_GAMES)
        unknown = {b.id for game in case.trophies.values() for b in game.badges if not b.info}
        assert not unknown, f"badges missing from badges.json: {sorted(unknown)}"
        return f"{sum(len(game.badges) for game in case.trophies.values())} badges"

    def bonus_states() -> str:
        last = datetime.datetime.now(NYT_TIMEZONE).date()
        rows = views.bonus_results(client, last - datetime.timedelta(days=29), last)
        return f"{sum(r['status'] != 'not played' for r in rows)} of {len(rows)} recent bonus puzzles played"

    def game_states(game: str, latest: Callable) -> Callable[[], str]:
        def check() -> str:
            last = datetime.datetime.now(NYT_TIMEZONE).date()
            first = last - datetime.timedelta(days=29)
            ids = [p.id for p in client.archive(game, first.isoformat(), last.isoformat())]
            return f"{len(latest(ids).states)} of {len(ids)} recent games played"
        return check

    return [("Player stats", stats), ("WordleBot", wordlebot), ("Badges", badges),
            ("Bonus Puzzles states", bonus_states),
            ("Connections states", game_states("connections", client.connections_latest)),
            ("Strands states", game_states("strands", client.strands_latest))]


def run(name: str, check: Callable[[], str]) -> dict:
    start = time.monotonic()
    try:
        detail, ok = check(), True
    except Exception as err:  # noqa: BLE001 - every failure is reported
        detail, ok = f"{type(err).__name__}: {err}"[:300], False
        traceback.print_exc()
    return {"name": name, "ok": ok, "detail": detail, "seconds": round(time.monotonic() - start, 2)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", help="Write the results as JSON.")
    parser.add_argument("--badge", help="Write a shields.io endpoint badge as JSON.")
    parser.add_argument("--summary", help="Append a Markdown summary (e.g. $GITHUB_STEP_SUMMARY).")
    args = parser.parse_args()

    now = datetime.datetime.now(NYT_TIMEZONE)
    selected = checks(NYTGamesClient(), now.date())
    if os.environ.get("NYT_COOKIES"):
        selected += user_checks(NYTGamesClient(cookies=os.environ["NYT_COOKIES"]))
    results = [run(name, check) for name, check in selected]
    passed = sum(r["ok"] for r in results)

    for r in results:
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['name']:<20} {r['detail']}")
    print(f"\n{passed}/{len(results)} checks passed")

    report = {"checked_at": now.isoformat(timespec="seconds"), "version": nytgames.__version__,
              "passed": passed, "total": len(results), "results": results}
    if args.json:
        with open(args.json, "w") as file:
            json.dump(report, file, indent=2)
    if args.badge:
        badge = {
            "schemaVersion": 1,
            "label": "NYT live check",
            "message": f"{passed}/{len(results)} passing · {now:%b} {now.day}",
            "color": "brightgreen" if passed == len(results) else "red",
        }
        with open(args.badge, "w") as file:
            json.dump(badge, file)
    if args.summary:
        with open(args.summary, "a") as file:
            file.write(f"## NYT live check: {passed}/{len(results)} passing\n\n"
                       f"{now:%Y-%m-%d %H:%M %Z}, nytimes-games {nytgames.__version__}\n\n"
                       "| | Check | Detail | Seconds |\n|---|---|---|---|\n")
            for r in results:
                detail = r["detail"].replace("|", "\\|")
                file.write(f"| {'✅' if r['ok'] else '❌'} | {r['name']} | {detail} | {r['seconds']} |\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())

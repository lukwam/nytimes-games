"""Badge tests: models, metadata and the trophy case endpoint, with NYT mocked.

Badge progress is made up; the shelf items are shaped like real responses.
"""
import json

import pytest

from nytgames.badges import all_badges
from nytgames.badges import badge_info
from nytgames.models import Badge
from nytgames.models import WordlePuzzlesList
from nytgames.views import badge_rows
from tests.support import COOKIES
from tests.support import NYT
from tests.support import USER_ID

# Trophy shelf items from real latests responses, with earned_at shortened.
WR6 = {"id": "wr6", "badge_type": "streak", "games": ["wordleV2"],
       "levels": [7, 14, 30, 60, 100, 150, 250, 365, 500, 750, 1000], "progress": 144,
       "earned_at": [1700000000, 1700100000, 1700200000, 1700300000, 1759700000], "last_earned_level": 100}
CX7 = {"id": "cx7", "badge_type": "progress", "games": ["connections"], "progress": 136,
       "earned_at": [1700000000], "earned": True}
ST4 = {"id": "st4", "badge_type": "milestone", "games": ["strands"],
       "levels": [25, 50, 75, 100, 250, 500, 750, 1000, 1250, 1500, 2000, 2500, 5000], "progress": 2696,
       "earned_at": list(range(1700000000, 1700000012)), "last_earned_level": 2500, "earned": True}
SB11 = {"id": "sb11", "badge_type": "holiday", "games": ["spelling_bee"], "levels": [2026], "progress": 0}


@pytest.mark.parametrize("shelf,ids", [([WR6, CX7], ["wr6", "cx7"]), ({}, []), (None, []), ({"wr6": WR6}, ["wr6"])])
def test_trophy_shelf(shelf, ids):
    """The trophy shelf is a list of badges; empty shelves can be {}."""
    latest = WordlePuzzlesList(user_id=1, states=[], badges_trophy_shelf=shelf)
    assert [badge.id for badge in latest.badges_trophy_shelf] == ids
    assert WordlePuzzlesList(user_id=1, states=[]).badges_trophy_shelf == []


@pytest.mark.parametrize("raw,earned,level,next_level,name", [
    (WR6, True, 100, 150, "100-day Streak"),
    (CX7, True, None, None, "Reverse Rainbow"),
    (ST4, True, 2500, 5000, "Found Theme Words"),
    (SB11, False, None, 2026, "Valentine Hat"),
    ({**SB11, "earned_years": [2026]}, True, 2026, None, "Valentine Hat"),
    ({"id": "sb8", "badge_type": "milestone", "levels": [1, 10, 25], "earned_at": [1]}, True, 1, 10, "Long Word"),
    # Trophy case: partly earned tiered badges are listed as unearned, without `earned`.
    ({"id": "sb4", "badge_type": "milestone", "levels": [5, 10, 750, 1000], "progress": 992,
      "earned_at": [1, 2, 3], "last_earned_level": 750}, True, 750, 1000, "Genius"),
    ({"id": "zz99", "newField": 1}, False, None, None, "zz99"),
])
def test_badge_progress(raw, earned, level, next_level, name):
    badge = Badge(**raw)
    assert (badge.is_earned, badge.level, badge.next_level, badge.name) == (earned, level, next_level, name)


def test_badge_metadata():
    """Every badge has a name and artwork, and text is filled in for a level."""
    badges = all_badges()
    assert len(badges) == 35
    assert all(b.displayName and b.imageUrl and b.games for b in badges)
    assert {b.id for b in all_badges("strands")} == {"st1", "st2", "st3", "st4"}
    assert badge_info("nope") is None

    wr6 = badge_info("wr6")
    assert wr6.name(30) == "30-day Streak"
    assert wr6.description(30, earned=True) == (
        "You earned this badge by completing 30 consecutive daily Wordle puzzles without losing.")
    assert wr6.image_url(30) == "https://www.nytimes.com/games-assets/v2/assets/badges/svgs/wr_streak_streak_30.svg"
    assert wr6.image_url(30, earned=False, dark=True).endswith("/streak_30_unearned_dark.svg")
    # Level 1 uses the singular text; progress badges say how many times they were earned.
    assert badge_info("st1").description(1).startswith("Earn this badge by completing 1 puzzle ")
    assert badge_info("cx7").description(earned=True, times=3).startswith("You earned this badge 3 times by ")
    assert badge_info("sb4").description(5).startswith("Subscribers can earn this badge by ")


async def test_trophy_case(logged_in, mock):
    """The trophy case lists every badge; partly earned badges are in both lists."""
    route = mock.get(f"{NYT}/svc/games/badges/trophy-case/wordleV2").respond(json={
        "user_id": USER_ID, "trophies": {"wordleV2": {"earned": [WR6], "unearned": [WR6, {"id": "wr2"}]}}})
    case = await logged_in("trophy_case", "wordleV2")
    assert route.call_count == 1
    assert route.calls.last.request.headers["Cookie"] == f"NYT-S={COOKIES['NYT-S']}"
    assert case.user_id == USER_ID
    assert [b.id for b in case.trophies["wordleV2"].badges] == ["wr6", "wr2"]
    with pytest.raises(ValueError):
        await logged_in("trophy_case", "wordle")
    assert len(mock.calls) == 1


async def test_badges_fetches_each_game(logged_in, mock):
    connections = mock.get(f"{NYT}/svc/games/badges/trophy-case/connections").respond(
        json={"user_id": USER_ID, "trophies": {"connections": {"earned": [CX7]}}})
    spelling_bee = mock.get(f"{NYT}/svc/games/badges/trophy-case/spelling_bee").respond(
        json={"user_id": USER_ID, "trophies": {"spelling_bee": {"unearned": [SB11]}}})
    case = await logged_in("badges", ["connections", "spelling_bee"])
    assert connections.call_count == 1 and spelling_bee.call_count == 1
    assert [str(call.request.url) for call in mock.calls] == [
        f"{NYT}/svc/games/badges/trophy-case/connections", f"{NYT}/svc/games/badges/trophy-case/spelling_bee"]
    assert case.user_id == USER_ID and list(case.trophies) == ["connections", "spelling_bee"]
    rows = badge_rows(case)
    assert [(r["game"], r["name"], r["earned"]) for r in rows] == [
        ("Connections", "Reverse Rainbow", True), ("Spelling Bee", "Valentine Hat", False)]
    assert rows[0]["description"].startswith("You earned this badge 136 times by ")
    assert rows[1]["image_url"].endswith("/sb_holiday_valentines-day_2026_unearned.svg")
    json.dumps(rows)

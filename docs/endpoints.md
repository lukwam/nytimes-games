# How NYT's games work

Notes on the endpoints behind the New York Times games, for contributors
and anyone curious. None of them are documented, so this is what they're
observed to do (as of October 2026) and may change.

Every endpoint is a GET. Paths are relative to `https://www.nytimes.com`
unless they're a full URL. Puzzles don't need cookies; everything about you
needs the `NYT-S` cookie.

## Sources

| Game | Puzzle | Archive | Answers in the data |
|---|---|---|---|
| Wordle | `/svc/wordle/v2/YYYY-MM-DD.json` | 2021-06-19 on | yes (`solution`) |
| Connections | `/svc/connections/v2/YYYY-MM-DD.json` | 2023-06-12 on | yes (`categories`) |
| Strands | `/svc/strands/v2/YYYY-MM-DD.json` | 2024-03-04 on | yes (`spangram`, `themeWords`) |
| Spelling Bee | `/svc/spelling-bee/v1/YYYY-MM-DD.json` | 2018-05-06 on | yes (`answers`, `pangrams`) |
| Letter Boxed | `/svc/letter-boxed/v1/YYYY-MM-DD.json` | 2018-12-17 on, with gaps | yes (`ourSolution`, every accepted word) |
| Crosswords | `/svc/crosswords/v6/puzzle/{type}/YYYY-MM-DD.json` | Daily 1993-11-21, Mini 2014-08-21, Midi 2026-02-25 | yes (each cell's `answer`) |
| Bonus Puzzles | `/svc/games/bonus/week/v1/YYYY-MM-DD.json` | 2026-08-26 on | yes, as for each game |

NYT usually serves the next day's puzzle a day early. A date with no puzzle
answers 404.

## Puzzles

- **Crosswords:**
  - `{type}` is `daily`, `mini`, `midi` or `bonus`.
  - `/svc/crosswords/v6/puzzle/{type}.json`, with no date, is today's puzzle.
    Bonus puzzles need a date.
  - `/svc/crosswords/v6/puzzle/{id}.json` gets any crossword by its ID.
    That's the only way to get both puzzles on a date that has two. NYT
    has removed its best-known example, 2022-12-31's 50x50 Supermega (its ID
    now answers 404), but the archive can still list two puzzles for a date.
  - `/svc/crosswords/v2/oracle/{type}.json` has the current and next
    puzzle's IDs and publish times.
- **Spelling Bee's game page:** `/puzzles/spelling-bee` has a
  `window.gameData = {...}` script with today's puzzle and the puzzles back
  to the start of last week. The dated JSON endpoint has the same fields
  and goes back to 2018.
- **Letter Boxed gaps:** 2018-12-21 to 2019-01-05 and 2019-01-25 have no
  puzzle.
- **Archive:** `/svc/games/v1/archive/{game}/{start}/{end}` lists puzzle IDs
  and print dates. `{game}` is `wordle`, `connections`, `strands`,
  `crossword_daily`, `crossword_mini` or `crossword_midi`.
  - It returns at most 31 puzzles per request, so a longer range is fetched
    31 days at a time. A window that returns 31 is split and fetched again,
    since a date with two puzzles can push one out.
  - Future dates aren't included.
- **WordleBot summary:**
  `https://static01.nyt.com/newsgraphics/2022/wordlebot/{solution}-{date}/summary.json`.
  It's named by the day's solution, so it needs the Wordle first. Summaries
  from 2021 to early 2022 can have null percentiles for a mode that had none
  yet.

## Bonus Puzzles

- **The week:** `/svc/games/bonus/week/v1/YYYY-MM-DD.json` returns
  `{"bonus_puzzles_week": {...}}`, the Wednesday drop that includes the
  date. Earlier dates return the first week. The next week's drop is served
  early, and a week that isn't published answers 404.
- **Each puzzle**, by the listing's `slug` (e.g. `2026-10-07-8`):
  - Wordle in 1: `/svc/wordle-in-one/v1/bonus/{slug}.json`
  - Connections 3x3: `/svc/connections/v2/bonus/{slug}.json`
  - Colorful Strands: `/svc/strands/v2/bonus/{slug}.json`
  - Crosswords (Mystery Mini, Easy Mode, Special): by ID, as above.

## You (needs `NYT-S`)

- **The cookie:** `NYT-S` from a signed-in nytimes.com browser. The client
  only sends cookies to `www.nytimes.com`, never to `static01.nyt.com`.
  Rejected or missing cookies answer 401 or 403.
- **Saved games:** `/svc/games/state/{game}/latests?puzzle_ids=1,2,3`.
  - `{game}` is `wordleV2`, `connections`, `strands`, `spelling_bee`,
    `crossword_daily`, `crossword_mini`, `crossword_midi`,
    `crossword_bonus`, `wordle_in_one`, `connections_bonus` or
    `strands_bonus`.
  - Up to 30 IDs per request; Spelling Bee answers 400 for more.
  - `states` only includes puzzles you've played.
  - Each response also has `badges_trophy_shelf`, the three badges featured
    for that game.
- **Stats:** there's no stats endpoint of its own. `player` in any
  `latests` response (the client asks for `wordleV2` with `puzzle_ids=0`)
  has streaks, win rates and distributions for every game. Accounts that
  have never played while signed in have no `player`.
- **Crossword list:** `/svc/crosswords/v3/puzzles.json` with `publish_type`,
  `date_start`, `date_end`, `sort_order` and `sort_by`, including your solved
  status and star.
  - At most 100 puzzles per request, and long ranges come back incomplete,
    so keep ranges to 90 days or less.
  - `publish_type=midi` returns Daily puzzles, so Midi progress needs the
    archive and `latests` instead.
- **WordleBot:**
  `/svc/int/run/cubby/public-api/v1/responses/wordlebot/reader` has your
  analysis of today's Wordle only, and only after you've opened WordleBot.
  Each time you open it adds an entry.
- **Badges:** `/svc/games/badges/trophy-case/{game}` for `wordleV2`,
  `connections`, `strands` and `spelling_bee` has every badge with your
  level and progress. Badge names, descriptions and artwork aren't served
  by any endpoint; they come from the games app, copied into
  `nytgames/badges.json`.
- **No history:** NYT keeps your saved game (its current state and totals),
  not individual moves.

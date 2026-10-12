"""NYT Games models."""
import datetime
from enum import Enum
from typing import Annotated
from typing import Any
from typing import Dict
from typing import List
from typing import TYPE_CHECKING
from pydantic import BaseModel
from pydantic import BeforeValidator
from pydantic import ConfigDict
from pydantic import Field

if TYPE_CHECKING:
    from nytgames.badges import BadgeInfo


class NYTModel(BaseModel):
    """Base model for NYT responses.

    Extra fields are allowed and passed through so that new fields added by
    NYT do not break validation.
    """
    model_config = ConfigDict(extra="allow")


class ConnectionsPuzzleCard(NYTModel):
    """Connections Puzzle Card.

    Most cards are words (`content`). Picture puzzles use image cards instead,
    with `image_url` and `image_alt_text`, and a puzzle can mix both.
    """
    content: str | None = None
    image_alt_text: str | None = None
    image_url: str | None = None
    position: int

    @property
    def text(self) -> str | None:
        """The card's word, or the alt text for an image card."""
        return self.content if self.content is not None else self.image_alt_text


class ConnectionsPuzzleCategory(NYTModel):
    """Connections Puzzle Category."""
    title: str
    cards: List[ConnectionsPuzzleCard]


class ConnectionsPuzzle(NYTModel):
    """Connections Puzzle."""
    id: int
    status: str
    print_date: str
    editor: str
    illustrator: str | None = None
    categories: List[ConnectionsPuzzleCategory]

    def board(self) -> List[List[ConnectionsPuzzleCard]]:
        """Return the cards as the starting board, in position order: 4x4, or
        3x3 for the Connections 3x3 bonus puzzle."""
        cards = sorted((card for category in self.categories for card in category.cards),
                       key=lambda card: card.position)
        width = len(self.categories) or 4
        return [cards[i:i + width] for i in range(0, len(cards), width)]


class ConnectionsGameData(NYTModel):
    """Connections Game Data (the user's saved progress).

    Older games vary in shape, so every field is optional.
    """
    guesses: List[Any] = []
    mistakes: int | None = None
    puzzleComplete: bool | None = None
    puzzleWon: bool | None = None
    solvedCategories: List[Any] = []
    isPlayingArchive: bool | None = None


class ConnectionsGameState(NYTModel):
    """Connections Game State."""
    game: str
    game_data: ConnectionsGameData
    # Often empty on older games; use puzzle_id instead.
    print_date: str = ""
    puzzle_id: str
    schema_version: str | None = None
    timestamp: int | None = None
    user_id: int
    version: str | None = None


class Badge(NYTModel):
    """A badge and your progress toward it.

    `badge_type` is progress, milestone, streak, challenge or holiday. Fields
    vary by type, so most are optional. `levels` are the thresholds for
    tiered badges (years, for holiday badges), and `earned_at` has a Unix
    timestamp for each level reached. Holiday badges list the years earned
    in `earned_years`.

    Names, descriptions and artwork come from `info` (see nytgames.badges).
    """
    id: str
    badge_type: str | None = None
    games: List[str] = []
    levels: List[int] = []
    progress: int | None = None
    earned_at: List[int] = []
    last_earned_level: int | None = None
    earned_years: List[int] = []
    earned: bool | None = None

    @property
    def is_earned(self) -> bool:
        """Whether you've earned this badge (at least its first level)."""
        if self.badge_type == "holiday":
            return bool(self.earned or self.earned_years)
        return bool(self.earned or self.earned_at or self.last_earned_level)

    @property
    def level(self) -> int | None:
        """The highest level you've earned (the latest year, for holiday badges)."""
        if self.badge_type == "holiday":
            return max(self.earned_years, default=None)
        if self.last_earned_level is not None:
            return self.last_earned_level
        if self.earned_at and self.levels:
            return self.levels[min(len(self.earned_at), len(self.levels)) - 1]
        return None

    @property
    def next_level(self) -> int | None:
        """The next level to earn, or None if you've earned them all."""
        if self.badge_type == "holiday":
            return next((year for year in self.levels if year not in self.earned_years), None)
        if not self.levels:
            return None
        current = self.level
        return next((level for level in self.levels if current is None or level > current), None)

    @property
    def earned_dates(self) -> List[datetime.datetime]:
        """`earned_at` as UTC datetimes."""
        return [datetime.datetime.fromtimestamp(t, datetime.timezone.utc) for t in self.earned_at]

    @property
    def info(self) -> "BadgeInfo | None":
        """The badge's name, description and artwork, or None for badges
        nytgames doesn't know yet."""
        from nytgames.badges import badge_info
        return badge_info(self.id)

    @property
    def name(self) -> str:
        """The badge's name at your level (or its first level), or its ID if unknown."""
        info = self.info
        return info.name(self.level) if info else self.id


def badge_list(value: Any) -> Any:
    """Return a trophy shelf as a list of badges. Empty shelves can be `{}`."""
    if isinstance(value, dict):
        return [badge for badge in value.values() if isinstance(badge, dict)]
    return [] if value is None else value


TrophyShelf = Annotated[List[Badge], BeforeValidator(badge_list)]


class BadgeGame(str, Enum):
    """Games with badges, by their NYT game name."""
    wordle = "wordleV2"
    connections = "connections"
    strands = "strands"
    spelling_bee = "spelling_bee"


class TrophyCaseGame(NYTModel):
    """One game's badges in the trophy case.

    `unearned` means not fully earned: tiered badges with levels still to
    reach are in `unearned` (and can be in `earned` too), with their
    `earned_at` and `last_earned_level`. Use `Badge.is_earned` and
    `Badge.level` rather than the list a badge is in.
    """
    earned: List[Badge] = []
    unearned: List[Badge] = []

    @property
    def badges(self) -> List[Badge]:
        """Every badge once, earned ones first."""
        seen = {badge.id for badge in self.earned}
        return [*self.earned, *(badge for badge in self.unearned if badge.id not in seen)]


class TrophyCase(NYTModel):
    """Every badge for one or more games, earned or not, keyed by game."""
    user_id: int | None = None
    trophies: Dict[str, TrophyCaseGame] = {}


class ConnectionsLatest(NYTModel):
    """Connections Game States."""
    player: "Player | None" = None
    states: List[ConnectionsGameState]
    user_id: int
    badges_trophy_shelf: TrophyShelf = []


class CrosswordGameData(NYTModel):
    """Crossword Game Data (the user's saved progress)."""
    cells: dict
    completionFraction: float | None = None
    firstSolve: int | None = None
    firstSolveDate: str | None = None
    playTimeSeconds: int | None = None
    star: str | None = None


class CrosswordGameState(NYTModel):
    """Crossword Game State."""
    game: str
    game_data: CrosswordGameData
    print_date: str = ""
    puzzle_id: str
    timestamp: int | None = None
    user_id: int


class CrosswordGame(NYTModel):
    """Crossword Game States."""
    player: "Player | None" = None
    states: List[CrosswordGameState]
    user_id: int
    badges_trophy_shelf: TrophyShelf = []


def number_or_text(value: Any) -> Any:
    """Return numeric strings as ints, and anything else unchanged."""
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


class CrosswordPuzzleCell(NYTModel):
    """Crossword Puzzle Cell."""
    answer: str | None = None
    clues: List[int] | None = None
    # Usually the clue number. Some special puzzles label squares with text,
    # such as "CW" or an arrow, which is kept as a string.
    label: Annotated[int | str | None, BeforeValidator(number_or_text)] = None
    # Rebus squares list other accepted answers, e.g. {"valid": ["L"]}.
    moreAnswers: Dict[str, List[str]] | None = None
    type: int | None = None


class CrosswordPuzzleClue(NYTModel):
    """Crossword Puzzle Clue."""
    cells: List[int]
    direction: str
    # Special clues, such as an "Around" clue, can have no label.
    label: str | None = None
    list: int | None = None
    relatives: List[int] | None = None
    text: List[Dict[str, str]]


class CrosswordPuzzleClueList(NYTModel):
    """Crossword Puzzle Clue List."""
    clues: List[int]
    name: str


class CrosswordPuzzleBody(NYTModel):
    """Crossword Puzzle Body."""
    board: str
    cells: List[CrosswordPuzzleCell]
    clues: List[CrosswordPuzzleClue]
    clueLists: List[CrosswordPuzzleClueList]
    dimensions: Dict[str, int]
    SVG: dict


class CrosswordPuzzle(NYTModel):
    """Crossword Puzzle (v6 format used by Daily, Mini, Midi and Bonus)."""
    id: int
    body: List[CrosswordPuzzleBody]
    constructors: List[str]
    copyright: str
    editor: str | None = None
    freePuzzle: bool | None = None
    lastUpdated: str
    notes: list | None = None
    publicationDate: str
    relatedContent: dict | None = None
    subcategory: int | None = None
    title: str | None = None

    def squares(self) -> list:
        """Return every square (a ``nytgames.structure.Square``), in reading order."""
        from nytgames.structure import squares
        return squares(self)

    def entries(self) -> list:
        """Return every entry (a ``nytgames.structure.Entry``) with its answer,
        squares, crossings and referenced clues, in clue list order."""
        from nytgames.structure import entries
        return entries(self)


class CrosswordOraclePuzzle(NYTModel):
    """Crossword Oracle Puzzle."""
    print_date: str
    published: str
    puzzle_id: int
    time_delta: int


class CrosswordOracleResults(NYTModel):
    """Crossword Oracle Results."""
    current: CrosswordOraclePuzzle
    next: CrosswordOraclePuzzle


class CrosswordOracle(NYTModel):
    """Crossword Oracle (current and next puzzle)."""
    results: CrosswordOracleResults
    status: str


# pylint: disable=invalid-name
class CrosswordPublishType(str, Enum):
    """Crossword Publish Type."""
    daily = "daily"
    bonus = "bonus"
    midi = "midi"
    mini = "mini"


class CrosswordPuzzleListItem(NYTModel):
    """Crossword Puzzle."""
    author: str
    editor: str
    format_type: str
    percent_filled: int
    print_date: str
    publish_type: str
    puzzle_id: int
    solved: bool
    star: str | None = None
    title: str
    version: int


class CrosswordPuzzlesList(NYTModel):
    """Crossword Puzzle List."""
    # NYT returns null instead of an empty list when there are no puzzles in
    # the range, and for ranges that are too long.
    results: Annotated[List[CrosswordPuzzleListItem], BeforeValidator(lambda v: v or [])] = []
    status: str


class ArchiveGame(str, Enum):
    """Games available from the games archive (``NYTGamesClient.archive``)."""
    connections = "connections"
    crossword_daily = "crossword_daily"
    crossword_midi = "crossword_midi"
    crossword_mini = "crossword_mini"
    strands = "strands"
    wordle = "wordle"


class ArchivePuzzle(NYTModel):
    """A puzzle in the games archive.

    Other fields depend on the game: crosswords have ``byline``, Strands has
    ``constructor`` and ``word_count``, and Wordle includes ``solution`` and
    ``days_since_launch``. They are kept as extra fields.
    """
    id: int
    print_date: str
    editor: str | None = None
    byline: str | None = None


class LetterBoxedPuzzle(NYTModel):
    """Letter Boxed Puzzle."""
    id: int
    dictionary: List[str]
    editor: str | None = None
    ourSolution: List[str]
    par: int
    printDate: str
    sides: List[str]


class SpellingBeeGameDay(NYTModel):
    """Spelling Bee Game Day."""
    id: int
    answers: List[str]
    centerLetter: str
    displayDate: str
    displayWeekday: str
    editor: str
    freeExpiration: int | None = None
    outerLetters: List[str]
    pangrams: List[str]
    printDate: str
    validLetters: List[str]


class SpellingBeePuzzle(NYTModel):
    """Spelling Bee Puzzle from the dated svc/spelling-bee/v1 endpoint.

    Note that `answers` does not include the pangrams. Use to_game_day() to get
    the same shape as the game page, with the full word list.
    """
    id: int
    answers: List[str]
    center_letter: str
    editor: str
    outer_letters: str
    pangrams: List[str]
    print_date: str

    def to_game_day(self) -> SpellingBeeGameDay:
        """Return the puzzle in the game page format.

        `answers` lists the pangrams first, as the game page does.
        `freeExpiration` is not available and is left unset.
        """
        date = datetime.date.fromisoformat(self.print_date)
        outer_letters = list(self.outer_letters)
        return SpellingBeeGameDay(
            id=self.id,
            answers=[*self.pangrams, *self.answers],
            centerLetter=self.center_letter,
            displayDate=f"{date:%B} {date.day}, {date.year}",
            displayWeekday=f"{date:%A}",
            editor=self.editor,
            outerLetters=outer_letters,
            pangrams=self.pangrams,
            printDate=self.print_date,
            validLetters=[self.center_letter, *outer_letters],
        )


class SpellingBeeGamePastPuzzles(NYTModel):
    """Spelling Bee Game Past Puzzles."""
    today: SpellingBeeGameDay
    yesterday: SpellingBeeGameDay
    lastWeek: List[SpellingBeeGameDay]
    thisWeek: List[SpellingBeeGameDay]


class SpellingBeeGameData(NYTModel):
    """Spelling Bee Game Data."""
    today: SpellingBeeGameDay
    yesterday: SpellingBeeGameDay
    pastPuzzles: SpellingBeeGamePastPuzzles


class SpellingBeeLongestWord(NYTModel):
    """Spelling Bee Longest Word"""
    word: str
    center_letter: str
    print_date: str


class SpellingBeeRanks(NYTModel):
    """Spelling Bee Ranks (number of puzzles finished at each rank)."""
    Amazing: int = 0
    Beginner: int = 0
    Genius: int = 0
    Good: int = 0
    Good_Start: int = Field(0, alias="Good Start")
    Great: int = 0
    Moving_Up: int = Field(0, alias="Moving Up")
    Nice: int = 0
    Queen_Bee: int = Field(0, alias="Queen Bee")
    Solid: int = 0


# Player stats
#
# These mirror the `player.stats` object NYT returns from the game state
# service. A game's stats are only present once the user has played it.


class SpellingBeeStats(NYTModel):
    """Spelling Bee Stats."""
    puzzles_started: int
    total_words: int
    total_pangrams: int
    longest_word: SpellingBeeLongestWord | None = None
    ranks: SpellingBeeRanks


class WordleGuesses(NYTModel):
    """Wordle wins by number of guesses."""
    one: int = Field(0, alias="1")
    two: int = Field(0, alias="2")
    three: int = Field(0, alias="3")
    four: int = Field(0, alias="4")
    five: int = Field(0, alias="5")
    six: int = Field(0, alias="6")
    fail: int = 0


class WordleLegacyStats(NYTModel):
    """Wordle Legacy Stats (daily games, including pre-NYT account history)."""
    currentStreak: int
    gamesPlayed: int
    gamesWon: int
    guesses: WordleGuesses
    hasPlayed: bool | None = None
    lastWonDayOffset: int | None = None
    maxStreak: int


class WordleCalculatedStats(NYTModel):
    """Wordle Calculated Stats (current streaks by print date)."""
    currentStreak: int
    hasPlayed: bool | None = None
    lastCompletedPrintDate: str | None = None
    lastWonPrintDate: str | None = None
    maxStreak: int


class WordleTotalStats(NYTModel):
    """Wordle Total Stats (all games, including the archive)."""
    gamesPlayed: int
    gamesWon: int
    guesses: WordleGuesses
    hasPlayed: bool | None = None
    hasPlayedArchive: bool | None = None


class WordleStats(NYTModel):
    """Wordle Stats.

    NYT reports three overlapping sets of Wordle stats that can disagree (for
    example the legacy and calculated current streaks), so they are kept
    separate rather than merged.
    """
    calculatedStats: WordleCalculatedStats | None = None
    legacyStats: WordleLegacyStats | None = None
    totalStats: WordleTotalStats | None = None


class ConnectionsStats(NYTModel):
    """Connections Stats."""
    current_streak: int
    last_played_print_date: str | None = None
    max_streak: int
    # Number of puzzles finished with 0 to 4 mistakes.
    mistakes: Dict[str, int]
    puzzles_completed: int
    puzzles_won: int


class StrandsStats(NYTModel):
    """Strands Stats."""
    current_streak: int
    last_played_print_date: str | None = None
    max_streak: int
    no_hints: int
    puzzles_completed: int
    puzzles_started: int
    spangram_first: int


class CrosswordStreak(NYTModel):
    """Crossword Streak."""
    current: int
    longest: int
    startDate: str | None = None


class CrosswordBestTime(NYTModel):
    """Crossword Best Time."""
    date: str | None = None
    timeSeconds: int


class CrosswordDayStats(NYTModel):
    """Crossword Daily Stats for one day of the week."""
    avgTimeSeconds: int
    best: CrosswordBestTime | None = None
    latestDate: str | None = None
    latestTimeSeconds: int | None = None
    thisWeeksDate: str | None = None
    thisWeeksTime: int | None = None
    totalSolveTime: int
    totalSolves: int
    verticalStreak: CrosswordStreak | None = None


class CrosswordDailyStats(NYTModel):
    """Crossword Daily Stats."""
    # Keyed by lowercase day of the week ("monday" to "sunday").
    dailyStats: Dict[str, CrosswordDayStats]
    dailyStreaks: CrosswordStreak | None = None
    puzzlesSolved: int
    puzzlesStarted: int
    solveRate: float


class CrosswordMiniStats(NYTModel):
    """Crossword Mini and Midi Stats."""
    avgTimeSeconds: int
    bestDate: str | None = None
    bestTimeSeconds: int | None = None
    puzzlesSolved: int
    puzzlesStarted: int
    solveRate: float
    streaks: CrosswordStreak | None = None


class PlayerStats(NYTModel):
    """Player Stats for every game the user has played."""
    connections: ConnectionsStats | None = None
    crossword_daily: CrosswordDailyStats | None = None
    crossword_midi: CrosswordMiniStats | None = None
    crossword_mini: CrosswordMiniStats | None = None
    spelling_bee: SpellingBeeStats | None = None
    strands: StrandsStats | None = None
    wordle: WordleStats | None = None


class Player(NYTModel):
    """Player."""
    account_creation_date: str | None = None
    last_updated: int | None = None
    stats: PlayerStats = PlayerStats()
    user_id: int | None = None


# Names used before the player stats models were shared across games.
SpellingBeeStatsSpellingBee = SpellingBeeStats
SpellingBeeStatsWordleLegacyStatsGuesses = WordleGuesses
SpellingBeeStatsWordleLegacyStats = WordleLegacyStats
SpellingBeeStatsWordle = WordleStats
SpellingBeePlayerStats = PlayerStats
SpellingBeePlayer = Player


class SpellingBeeLatestStateGameData(NYTModel):
    """Spelling Bee Latest State Game Data.

    Older games have no `rank`.
    """
    answers: List[str] = []
    isRevealed: bool | None = None
    isPlayingArchive: bool | None = None
    rank: str | None = None


class SpellingBeeLatestState(NYTModel):
    """Spelling Bee Latest State."""
    game_data: SpellingBeeLatestStateGameData
    game: str
    # Often empty on older games; use puzzle_id instead.
    print_date: str = ""
    puzzle_id: str
    schema_version: str | None = None
    timestamp: int | None = None
    user_id: int
    version: str | None = None


class SpellingBeeLatest(NYTModel):
    """Spelling Bee Latest."""
    user_id: int
    states: List[SpellingBeeLatestState]
    player: Player | None = None
    badges_trophy_shelf: TrophyShelf = []


class StrandsPuzzle(NYTModel):
    """Strands Puzzle."""
    id: int
    clue: str
    constructors: str | None = None
    editor: str
    printDate: str
    solutions: List[str]
    spangram: str
    startingBoard: List[str]
    themeCoords: Dict[str, List[List[int]]]
    spangramCoords: List[List[int]] | None = None
    themeWords: List[str] | None = []
    title: str | None = None
    # Colorful Strands (a bonus puzzle): each theme word's color and emoji.
    themeColors: Dict[str, str] | None = None
    themeEmojis: Dict[str, str] | None = None

    def words(self) -> list:
        """Return the theme words and spangram (``nytgames.structure.StrandsWord``)
        with their paths through the board."""
        from nytgames.structure import strands_words
        return strands_words(self)


class StrandsGameData(NYTModel):
    """Strands Game Data (the user's saved progress).

    Older games vary in shape, so every field is optional.
    """
    history: List[Any] = []
    isSolved: bool | None = None
    otherWordsFound: List[str] = []
    isPlayingArchive: bool | None = None


class StrandsGameState(NYTModel):
    """Strands Game State."""
    game: str
    game_data: StrandsGameData
    # Often empty on older games; use puzzle_id instead.
    print_date: str = ""
    puzzle_id: str
    schema_version: str | None = None
    timestamp: int | None = None
    user_id: int
    version: str | None = None


class StrandsLatest(NYTModel):
    """Strands Game States."""
    player: Player | None = None
    states: List[StrandsGameState]
    user_id: int
    badges_trophy_shelf: TrophyShelf = []


class WordlePuzzle(NYTModel):
    """Wordle Puzzle."""
    id: int
    days_since_launch: int | None = None
    editor: str | None = None
    print_date: str
    solution: str


class WordleRound(NYTModel):
    """One round of a Wordle game in the rounds-based format."""
    complete: bool | None = None
    timeMs: int | None = None


class WordleGameData(NYTModel):
    """Wordle Game Data (the user's saved progress).

    Most games have `boardState`, `currentRowIndex` and `status`. Some saved
    games use a different, rounds-based format with `rounds`,
    `currentRoundIndex` and `puzzleComplete` instead (and no guesses).
    """
    boardState: List[str] = []
    currentRowIndex: int | None = None
    hardMode: bool | None = None
    isPlayingArchive: bool | None = None
    status: str | None = None
    currentRoundIndex: int | None = None
    puzzleComplete: bool | None = None
    rounds: List[WordleRound] = []

    @property
    def rounds_format(self) -> bool:
        """Whether this game is in the rounds-based format, without guesses."""
        return self.status is None and (bool(self.rounds) or self.puzzleComplete is not None)


class WordleGameState(NYTModel):
    """Wordle Game State."""
    game: str
    game_data: WordleGameData
    # Often empty on older games; use puzzle_id instead.
    print_date: str = ""
    puzzle_id: str
    schema_version: str | None = None
    timestamp: int | None = None
    user_id: int
    version: str | None = None


class WordlePuzzlesList(NYTModel):
    """Wordle Game States."""
    player: Player | None = None
    states: List[WordleGameState]
    user_id: int
    badges_trophy_shelf: TrophyShelf = []


CrosswordGame.model_rebuild()
ConnectionsLatest.model_rebuild()


class WordleInOneRound(NYTModel):
    """One round of Wordle in 1: a starting guess, and the only word that fits."""
    start: str
    solution: str


class WordleInOnePuzzle(NYTModel):
    """Wordle in 1, a weekly bonus puzzle: five rounds, each solved in one guess."""
    id: int
    slug: str
    title: str | None = None
    print_date: str
    editor: str | None = None
    stream: str | None = None
    make_free: bool | None = None
    rounds: List[WordleInOneRound]


class WordleInOneGameData(NYTModel):
    """Wordle in 1 Game Data (the user's saved progress)."""
    currentRoundIndex: int | None = None
    puzzleComplete: bool | None = None
    rounds: List[WordleRound] = []
    isPlayingArchive: bool | None = None

    @property
    def rounds_solved(self) -> int:
        return sum(1 for r in self.rounds if r.complete)

    @property
    def seconds(self) -> float | None:
        """Total solving time across rounds."""
        return sum(r.timeMs or 0 for r in self.rounds) / 1000 if self.rounds else None


class WordleInOneGameState(NYTModel):
    """Wordle in 1 Game State."""
    game: str
    game_data: WordleInOneGameData
    print_date: str = ""
    puzzle_id: str
    schema_version: str | None = None
    timestamp: int | None = None
    user_id: int
    version: str | None = None


class WordleInOneLatest(NYTModel):
    """Wordle in 1 Game States."""
    player: Player | None = None
    states: List[WordleInOneGameState]
    user_id: int
    badges_trophy_shelf: TrophyShelf = []


class BonusPuzzleListing(NYTModel):
    """A puzzle in a week's Bonus Puzzles drop.

    `game` is wordle-in-one, connections, strands or crossword, and
    `variant` is standard, 3x3, colorful, mini, easy or monthly so far.
    `slug` fetches Wordle in 1, Connections and Strands puzzles; crosswords
    are fetched by `id`.
    """
    game: str
    variant: str | None = None
    title: str | None = None
    subtitle: str | None = None
    editors: List[str] = []
    constructors: str | None = None
    card_byline: str | None = None
    make_free: bool | None = None
    id: int
    slug: str
    web_url: str | None = None


class BonusWeek(NYTModel):
    """A week's Bonus Puzzles drop. Drops come out on Wednesdays.

    `display_free` is true for weeks free to everyone (such as the first,
    2026-08-26); other weeks are for subscribers on NYT's site.
    """
    drop_date: str
    prev_drop: str | None = None
    next_drop: str | None = None
    display_free: bool | None = None
    week_in_month: int | None = None
    puzzles: List[BonusPuzzleListing] = []


class WordleBotAnalysis(NYTModel):
    """Your WordleBot analysis of a Wordle game.

    `luck` and `efficiency` (WordleBot's skill score) are from 0 to 1, for
    the whole game and for each round.
    """
    gameNumber: int
    guesses: str
    mode: str | None = None
    luck: float | None = None
    efficiency: float | None = None
    luckByRound: List[float] = []
    efficiencyByRound: List[float] = []
    solution: str | None = None
    solutionsRemaining: int | None = None
    created_at: str | None = None
    response_id: str | None = None

    @property
    def guess_list(self) -> List[str]:
        """Your guesses as a list."""
        return [guess for guess in self.guesses.split("-") if guess]


class WordleBotSummary(NYTModel):
    """How everyone did on a day's Wordle, from WordleBot.

    Most values are keyed by mode: "normal" and "hard", and in recent years
    "normal-ps" and "hard-ps". `steps` lists how many players solved it in
    1 to 6 guesses and how many didn't. `percentiles` are of the skill
    (`efficiency`) score. `guesses` has the bot's solve paths, keyed by
    strategy such as "normal-simple", and includes the solution.
    """
    average: Dict[str, float | None] | None = None
    botUserAverage: Dict[str, float | None] | None = None
    efficiency: Dict[str, float | None] | None = None
    luck: Dict[str, float | None] | None = None
    steps: Dict[str, Any] | None = None
    botUserSteps: Dict[str, Any] | None = None
    unsolvedPenalty: Dict[str, float | None] | None = None
    percentSolvingInThreeOrFewer: Dict[str, float | None] | None = None
    # A mode is null on days before it had percentiles (2021 and early 2022).
    percentiles: Dict[str, Dict[str, float | None] | None] | None = None
    guesses: Dict[str, List[str]] | None = None

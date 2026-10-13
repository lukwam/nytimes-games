"""Unofficial client for the New York Times Games APIs."""
__version__ = "0.11.3"

from nytgames.client import AsyncNYTGamesClient  # noqa: E402
from nytgames.client import NYTGamesClient  # noqa: E402
from nytgames.client import parse_cookies  # noqa: E402
from nytgames.exceptions import NYTGamesAuthenticationError  # noqa: E402
from nytgames.exceptions import NYTGamesError  # noqa: E402
from nytgames.exceptions import NYTGamesExportError  # noqa: E402
from nytgames.exceptions import NYTGamesHTTPError  # noqa: E402
from nytgames.exceptions import NYTGamesNoProfileError  # noqa: E402
from nytgames.exceptions import NYTGamesNotFoundError  # noqa: E402
from nytgames.exceptions import NYTGamesParseError  # noqa: E402
from nytgames.exceptions import NYTGamesRateLimitError  # noqa: E402
from nytgames.models import ArchiveGame  # noqa: E402
from nytgames.models import CrosswordPublishType  # noqa: E402
from nytgames.spelling_bee import spelling_bee_hints  # noqa: E402

__all__ = [
    "ArchiveGame",
    "AsyncNYTGamesClient",
    "CrosswordPublishType",
    "NYTGamesAuthenticationError",
    "NYTGamesClient",
    "NYTGamesError",
    "NYTGamesExportError",
    "NYTGamesHTTPError",
    "NYTGamesNotFoundError",
    "NYTGamesNoProfileError",
    "NYTGamesParseError",
    "NYTGamesRateLimitError",
    "parse_cookies",
    "spelling_bee_hints",
]

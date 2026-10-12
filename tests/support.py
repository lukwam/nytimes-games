"""Shared test helpers: fixture files, fake cookies and a sync/async client wrapper.

The fixtures in tests/fixtures are captures of real NYT responses, saved
byte for byte; the Spelling Bee page is trimmed to its game data script.
Saved games, stats and user IDs are made up, in the tests themselves.
"""
import json
from contextlib import contextmanager
from pathlib import Path

import respx

from nytgames import AsyncNYTGamesClient
from nytgames import NYTGamesClient

FIXTURES = Path(__file__).parent / "fixtures"
NYT = "https://www.nytimes.com"
#: A made-up NYT user ID.
USER_ID = 123456789
#: A made-up NYT-S cookie.
COOKIES = {"NYT-S": "0^made-up-session-cookie"}


def text(path: str) -> str:
    return (FIXTURES / path).read_text(encoding="utf-8")


def load(path: str):
    return json.loads(text(path))


@contextmanager
def nyt_mock():
    """A respx router for NYT that fails the test if anything but a GET is sent.

    The library is read-only: every request any test makes must be a GET.
    """
    with respx.mock(assert_all_called=False) as router:
        yield router
    for call in router.calls:
        assert call.request.method == "GET", call.request


class Api:
    """Calls a client method the same way for the sync and async clients."""

    def __init__(self, kind: str, **kwargs):
        self.kind = kind
        kwargs.setdefault("backoff", 0)
        cls = NYTGamesClient if kind == "sync" else AsyncNYTGamesClient
        self.client = cls(**kwargs)

    async def __call__(self, name: str, *args, **kwargs):
        result = getattr(self.client, name)(*args, **kwargs)
        if self.kind == "async":
            result = await result
        return result

"""AsyncNYTGamesClient tests, with httpx.MockTransport standing in for NYT."""
import asyncio
import json

import httpx
import pytest

from nytgames import AsyncNYTGamesClient
from nytgames import NYTGamesAuthenticationError
from nytgames import NYTGamesClient
from nytgames import NYTGamesNotFoundError
from nytgames import NYTGamesRateLimitError
from nytgames.models import WordlePuzzle

WORDLE = {"id": 1, "solution": "cigar", "print_date": "2021-06-19"}


def client_for(handler, **kwargs) -> AsyncNYTGamesClient:
    kwargs.setdefault("backoff", 0)

    def get_only(request):
        # The library is read-only: every request any async test makes must be a GET.
        assert request.method == "GET", request
        return handler(request)

    return AsyncNYTGamesClient(http_client=httpx.AsyncClient(transport=httpx.MockTransport(get_only)), **kwargs)


def run(coro):
    return asyncio.run(coro)


def test_sync_and_async_clients_have_the_same_methods():
    def public(cls):
        return {n for n in dir(cls) if not n.startswith("_") and callable(getattr(cls, n))}
    assert public(NYTGamesClient) == public(AsyncNYTGamesClient) - {"aclose"}
    assert NYTGamesClient.wordle.__doc__ == AsyncNYTGamesClient.wordle.__doc__
    assert asyncio.iscoroutinefunction(AsyncNYTGamesClient.wordle)


def test_requests_and_cookies():
    """Requests match the sync client: same URLs, User-Agent, and cookies only for nytimes.com."""
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.host == "static01.nyt.com":
            return httpx.Response(200, json={"date": "2021-06-19"})
        return httpx.Response(200, json=WORDLE)

    async def go():
        async with client_for(handler, cookies="NYT-S=abc") as client:
            puzzle = await client.wordle("2021-06-19")
            await client.wordlebot_summary("2021-06-19")
        return puzzle

    puzzle = run(go())
    assert isinstance(puzzle, WordlePuzzle) and puzzle.solution == "cigar"
    assert str(seen[0].url) == "https://www.nytimes.com/svc/wordle/v2/2021-06-19.json"
    assert seen[0].headers["Cookie"] == "NYT-S=abc"
    assert seen[0].headers["User-Agent"].startswith("nytimes-games/")
    # wordlebot_summary fetches the Wordle (with cookies), then NYT's static file (without).
    assert seen[-1].url.host == "static01.nyt.com" and "Cookie" not in seen[-1].headers


def test_params_and_operations_that_call_others():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json={"user_id": 1, "trophies": {request.url.path.rsplit("/", 1)[1]: {}}})

    case = run(client_for(handler).badges(["wordleV2", "strands"]))
    assert list(case.trophies) == ["wordleV2", "strands"]
    assert [u.path for u in seen] == ["/svc/games/badges/trophy-case/wordleV2", "/svc/games/badges/trophy-case/strands"]

    seen.clear()
    run(client_for(lambda r: (seen.append(r.url), httpx.Response(200, json={"user_id": 1, "states": []}))[1])
        .wordle_latest([1, 2]))
    assert seen[0].params["puzzle_ids"] == "1,2"


@pytest.mark.parametrize("status,error", [
    (404, NYTGamesNotFoundError),
    (403, NYTGamesAuthenticationError),
])
def test_errors(status, error):
    with pytest.raises(error) as info:
        run(client_for(lambda r: httpx.Response(status)).wordle("2021-06-19"))
    assert info.value.response.status_code == status


def test_retries_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json=WORDLE)

    assert run(client_for(handler).wordle("2021-06-19")).id == 1
    assert len(calls) == 3


def test_rate_limit_after_retries():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, headers={"Retry-After": "0"})

    with pytest.raises(NYTGamesRateLimitError) as info:
        run(client_for(handler, retries=2).wordle("2021-06-19"))
    assert len(calls) == 3 and info.value.retry_after == 0


def test_connection_errors_are_retried():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json=WORDLE)

    assert run(client_for(handler).wordle("2021-06-19")).solution == "cigar"
    with pytest.raises(httpx.ConnectError):
        run(client_for(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")), retries=1).wordle("x"))


def test_errors_reach_operations():
    """Errors are thrown into operations, so bonus_weeks can stop at an unpublished week."""
    week = {"drop_date": "2026-10-07", "prev_drop": "2026-09-30", "next_drop": "2026-10-14", "puzzles": []}

    def handler(request):
        if request.url.path.endswith("2026-10-07.json"):
            return httpx.Response(200, json={"bonus_puzzles_week": week})
        return httpx.Response(404)

    weeks = run(client_for(handler).bonus_weeks("2026-10-07", "2026-12-31"))
    assert [w.drop_date for w in weeks] == ["2026-10-07"]


def test_html_page():
    """Spelling Bee's game page is read as HTML, not JSON."""
    day = {"displayWeekday": "Monday", "displayDate": "June 12, 2025", "printDate": "2025-06-12",
           "centerLetter": "a", "outerLetters": list("bcdefg"), "validLetters": list("abcdefg"),
           "pangrams": [], "answers": [], "id": 1, "freeExpiration": 0, "editor": "Sam Ezersky"}
    game_data = {"today": day, "yesterday": day,
                 "pastPuzzles": {"today": day, "yesterday": day, "thisWeek": [], "lastWeek": []}}
    page = f"<html><script>window.gameData = {json.dumps(game_data)}</script></html>"

    def handler(request):
        assert "Accept" not in request.headers or request.headers["Accept"] != "application/json"
        return httpx.Response(200, text=page)

    assert run(client_for(handler).spelling_bee()).today.printDate == "2025-06-12"


def test_lifecycle():
    async def go():
        async with AsyncNYTGamesClient() as client:
            http = client.http_client
        own = httpx.AsyncClient()
        async with AsyncNYTGamesClient(http_client=own):
            pass
        closed = own.is_closed
        await own.aclose()
        return http.is_closed, closed

    assert run(go()) == (True, False)

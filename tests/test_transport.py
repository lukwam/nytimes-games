"""Transport tests: retries, error mapping, decoding and cookies.

Every test runs with both the sync and the async driver.
"""
import datetime
import email.utils

import httpx
import pytest

from nytgames import NYTGamesAuthenticationError
from nytgames import NYTGamesHTTPError
from nytgames import NYTGamesNotFoundError
from nytgames import NYTGamesParseError
from nytgames import NYTGamesRateLimitError
from nytgames import transport
from nytgames.transport import Request
from nytgames.transport import Settings

URL = "https://www.nytimes.com/svc/data.json"


@pytest.fixture(params=["sync", "async"])
def kind(request):
    return request.param


@pytest.fixture
def sleeps(monkeypatch):
    """Record backoff sleeps instead of sleeping."""
    calls = []

    async def asleep(seconds):
        calls.append(seconds)

    monkeypatch.setattr(transport.time, "sleep", calls.append)
    monkeypatch.setattr(transport.asyncio, "sleep", asleep)
    return calls


def settings(**kwargs) -> Settings:
    return Settings(**{"cookies": {}, "user_agent": "test-agent", **kwargs})


async def run(kind: str, operation, config: Settings | None = None):
    config = config or settings()
    if kind == "sync":
        with httpx.Client() as client:
            return transport.run_sync(client, config, operation)
    async with httpx.AsyncClient() as client:
        return await transport.run_async(client, config, operation)


def get(request: Request):
    """An operation that makes one request and returns its result."""
    return (yield request)


async def test_server_errors_and_rate_limits_are_retried_with_backoff(kind, mock, sleeps):
    route = mock.get(URL).mock(side_effect=[
        httpx.Response(503), httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(502),
        httpx.Response(200, json={"ok": True})])
    assert await run(kind, get(Request(URL))) == {"ok": True}
    assert route.call_count == 4
    # 0.5 * 2**attempt, or Retry-After when that's longer
    assert sleeps == [0.5, 3.0, 2.0]


async def test_rate_limit_error_after_retries(kind, mock, sleeps):
    route = mock.get(URL).mock(return_value=httpx.Response(429, headers={"Retry-After": "0"}))
    with pytest.raises(NYTGamesRateLimitError) as info:
        await run(kind, get(Request(URL)), settings(retries=2))
    assert route.call_count == 3
    assert info.value.retry_after == 0
    assert info.value.status_code == 429 and info.value.response.status_code == 429
    assert isinstance(info.value, NYTGamesHTTPError)


async def test_retries_can_be_turned_off(kind, mock, sleeps):
    route = mock.get(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(NYTGamesHTTPError) as info:
        await run(kind, get(Request(URL)), settings(retries=0))
    assert route.call_count == 1 and sleeps == []
    assert info.value.status_code == 503
    assert type(info.value) is NYTGamesHTTPError


async def test_connection_errors_are_retried_then_raised(kind, mock, sleeps):
    route = mock.get(URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(httpx.ConnectError):
        await run(kind, get(Request(URL)), settings(retries=2))
    assert route.call_count == 3
    assert sleeps == [0.5, 1.0]


async def test_connection_error_then_success(kind, mock, sleeps):
    mock.get(URL).mock(side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json=[1])])
    assert await run(kind, get(Request(URL))) == [1]


@pytest.mark.parametrize("status,request_kwargs,error,message", [
    (404, {}, NYTGamesNotFoundError, "HTTP 404"),
    (404, {"not_found": "No puzzle"}, NYTGamesNotFoundError, "No puzzle"),
    (403, {}, NYTGamesAuthenticationError, "HTTP 403"),
    (401, {}, NYTGamesAuthenticationError, "HTTP 401"),
    (400, {}, NYTGamesHTTPError, "HTTP 400"),
])
async def test_client_errors_are_typed_and_not_retried(kind, mock, sleeps, status, request_kwargs, error, message):
    route = mock.get(URL).mock(return_value=httpx.Response(status))
    with pytest.raises(error, match=message) as info:
        await run(kind, get(Request(URL, **request_kwargs)))
    assert route.call_count == 1 and sleeps == []
    assert info.value.status_code == status


def test_retry_after_formats():
    def response(value):
        return httpx.Response(429, headers={"Retry-After": value} if value is not None else {})
    assert transport.retry_after(response("12")) == 12
    assert transport.retry_after(response("1.5")) == 1.5
    assert transport.retry_after(response("-4")) == 0
    assert transport.retry_after(response(None)) is None
    assert transport.retry_after(response("soon")) is None
    # Non-finite numbers fall back to the backoff instead of waiting forever.
    for value in ("inf", "-inf", "nan", "1e999"):
        assert transport.retry_after(response(value)) is None, value


def test_retry_after_dates_use_the_clock(monkeypatch):
    now = datetime.datetime(2026, 10, 12, 12, 0, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(transport, "_utcnow", lambda: now)

    def response(when):
        return httpx.Response(429, headers={"Retry-After": email.utils.format_datetime(when, usegmt=True)})
    assert transport.retry_after(response(now + datetime.timedelta(seconds=30))) == 30
    assert transport.retry_after(response(now + datetime.timedelta(hours=1))) == 3600
    assert transport.retry_after(response(now - datetime.timedelta(days=1))) == 0


def test_the_backoff_is_capped_but_retry_after_is_not():
    config = settings(backoff=10)
    assert transport._delay(config, 5, None) == transport.BACKOFF_CAP == 60
    # A Retry-After within the limit is honored in full, beyond the backoff cap.
    assert transport._delay(config, 0, httpx.Response(429, headers={"Retry-After": "120"})) == 120
    assert transport._delay(config, 0, httpx.Response(429, headers={"Retry-After": "300"})) == 300


async def test_retry_after_up_to_the_limit_is_waited_for(kind, mock, sleeps):
    route = mock.get(URL).mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": str(transport.RETRY_AFTER_LIMIT)}),
        httpx.Response(503, headers={"Retry-After": "120"}), httpx.Response(200, json={"ok": True})])
    assert await run(kind, get(Request(URL))) == {"ok": True}
    assert route.call_count == 3 and sleeps == [300.0, 120.0]


@pytest.mark.parametrize("status,error", [(429, NYTGamesRateLimitError), (503, NYTGamesHTTPError)])
async def test_a_longer_retry_after_raises_at_once_instead_of_retrying_early(kind, mock, sleeps, status, error):
    """Never retry sooner than the server asked (#64): past the limit, the
    error is raised without waiting, with the requested wait."""
    route = mock.get(URL).mock(return_value=httpx.Response(status, headers={"Retry-After": "3600"}))
    with pytest.raises(error) as info:
        await run(kind, get(Request(URL)))
    assert route.call_count == 1 and sleeps == []
    assert info.value.status_code == status
    if status == 429:
        assert info.value.retry_after == 3600


async def test_malformed_retry_after_falls_back_to_the_backoff(kind, mock, sleeps):
    route = mock.get(URL).mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "soon"}), httpx.Response(429, headers={"Retry-After": "inf"}),
        httpx.Response(200, json={"ok": True})])
    assert await run(kind, get(Request(URL))) == {"ok": True}
    assert route.call_count == 3 and sleeps == [0.5, 1.0]


async def test_text_json_and_headers(kind, mock):
    route = mock.get(URL).mock(return_value=httpx.Response(200, text="<html>hi</html>"))
    assert await run(kind, get(Request(URL, {"a": 1, "b": None}, kind="text"))) == "<html>hi</html>"
    sent = route.calls.last.request
    assert dict(sent.url.params) == {"a": "1"}  # unset params aren't sent
    assert sent.headers["User-Agent"] == "test-agent"
    assert "Accept" not in sent.headers or sent.headers["Accept"] != "application/json"
    with pytest.raises(NYTGamesParseError, match="Expected JSON"):
        await run(kind, get(Request(URL)))  # e.g. a bot check page
    assert route.calls.last.request.headers["Accept"] == "application/json"


async def test_relative_urls_use_the_base_url(kind, mock):
    route = mock.get("https://nyt.example.test/svc/data.json").mock(return_value=httpx.Response(200, json={}))
    await run(kind, get(Request("/svc/data.json")), settings(base_url="https://nyt.example.test"))
    assert route.called


async def test_cookies_only_go_to_nyt(kind, mock):
    """Cookies go to www.nytimes.com and the base URL, never to other hosts."""
    nyt = mock.get(URL).mock(return_value=httpx.Response(200, json={}))
    static = mock.get("https://static01.nyt.com/data.json").mock(return_value=httpx.Response(200, json={}))
    proxy = mock.get("https://nyt.example.test/svc/data.json").mock(return_value=httpx.Response(200, json={}))
    config = settings(cookies={"NYT-S": "secret", "nyt-a": "x"}, base_url="https://nyt.example.test")
    await run(kind, get(Request(URL)), config)
    assert nyt.calls.last.request.headers["Cookie"] == "NYT-S=secret; nyt-a=x"
    await run(kind, get(Request("/svc/data.json")), config)
    assert proxy.calls.last.request.headers["Cookie"] == "NYT-S=secret; nyt-a=x"
    await run(kind, get(Request("https://static01.nyt.com/data.json")), config)
    assert "Cookie" not in static.calls.last.request.headers
    await run(kind, get(Request(URL)))  # no cookies, no header
    assert "Cookie" not in nyt.calls.last.request.headers


async def test_errors_are_thrown_into_operations(kind, mock):
    """An operation can catch a request's error and carry on."""
    missing = "https://www.nytimes.com/svc/missing.json"
    mock.get(missing).mock(return_value=httpx.Response(404))
    mock.get(URL).mock(return_value=httpx.Response(200, json={"fallback": True}))

    def operation():
        try:
            yield Request(missing)
        except NYTGamesNotFoundError as error:
            caught = error.status_code
        data = yield Request(URL)
        return caught, data

    assert await run(kind, operation()) == (404, {"fallback": True})


async def test_operation_can_return_from_an_error(kind, mock):
    mock.get(URL).mock(return_value=httpx.Response(404))

    def operation():
        try:
            yield Request(URL)
        except NYTGamesNotFoundError:
            return None

    assert await run(kind, operation()) is None


async def test_operation_without_requests(kind):
    def operation():
        return "no requests"
        yield  # pragma: no cover

    assert await run(kind, operation()) == "no requests"

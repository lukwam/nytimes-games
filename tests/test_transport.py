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
    later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=30)
    assert 25 < transport.retry_after(response(email.utils.format_datetime(later, usegmt=True))) <= 30
    past = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)
    assert transport.retry_after(response(email.utils.format_datetime(past, usegmt=True))) == 0


def test_delay_is_capped():
    config = settings(backoff=10)
    assert transport._delay(config, 5, None) == 60
    assert transport._delay(config, 0, httpx.Response(429, headers={"Retry-After": "3600"})) == 60


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

"""HTTP for the sync and async clients.

Client operations are written once, as generators that yield `Request`s and
receive the decoded responses. `run_sync` drives one with an `httpx.Client`,
`run_async` with an `httpx.AsyncClient`, so both clients share every URL,
parser and error rule.
"""
import asyncio
import datetime
import email.utils
import logging
import math
import time
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Generator

import httpx

from nytgames.exceptions import NYTGamesAuthenticationError
from nytgames.exceptions import NYTGamesHTTPError
from nytgames.exceptions import NYTGamesNotFoundError
from nytgames.exceptions import NYTGamesParseError
from nytgames.exceptions import NYTGamesRateLimitError

logger = logging.getLogger("nytgames")

NYT_BASE_URL = "https://www.nytimes.com"
RETRY_STATUSES = (429, 500, 502, 503, 504)
#: The longest the client's own exponential backoff waits between retries.
BACKOFF_CAP = 60
#: The longest Retry-After the client waits for. A server that asks for
#: longer gets no early retry: the error is raised at once, with its
#: `retry_after`, so the caller can decide when to try again.
RETRY_AFTER_LIMIT = 300


@dataclass
class Request:
    """One GET request.

    `url` is relative to the client's `base_url`, or a full URL. `kind` is
    how to decode the body: "json" or "text". `not_found` is the message for
    a 404.
    """
    url: str
    params: dict[str, Any] = field(default_factory=dict)
    kind: str = "json"
    headers: dict[str, str] = field(default_factory=dict)
    not_found: str | None = None


Operation = Generator[Request, Any, Any]


@dataclass
class Settings:
    """What both clients need to send requests."""
    cookies: dict[str, str]
    user_agent: str
    retries: int = 3
    backoff: float = 0.5
    base_url: str = NYT_BASE_URL


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def retry_after(response: httpx.Response) -> float | None:
    """Return the seconds a response's Retry-After asks to wait (seconds or
    an HTTP date), or None if it's absent or malformed."""
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        pass
    else:
        return max(0.0, seconds) if math.isfinite(seconds) else None
    try:
        when = email.utils.parsedate_to_datetime(value)
        return max(0.0, (when - _utcnow()).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def _delay(settings: Settings, attempt: int, response: httpx.Response | None) -> float:
    """The wait before the next attempt: the exponential backoff (capped at
    BACKOFF_CAP), or the response's Retry-After when that's longer."""
    wait = min(settings.backoff * (2 ** attempt), BACKOFF_CAP)
    after = retry_after(response) if response is not None else None
    return max(wait, after or 0)


def _should_retry(settings: Settings, attempt: int, response: httpx.Response | None) -> bool:
    if attempt >= settings.retries:
        return False
    if response is None:
        return True
    if response.status_code not in RETRY_STATUSES:
        return False
    # Never retry before the server said to: a longer wait than we're willing
    # to make raises the error now instead.
    after = retry_after(response)
    return after is None or after <= RETRY_AFTER_LIMIT


def _build(settings: Settings, request: Request) -> dict:
    url = request.url if request.url.startswith("https://") else settings.base_url + request.url
    headers = {"User-Agent": settings.user_agent, **request.headers}
    if request.kind != "text":
        headers["Accept"] = "application/json"
    if settings.cookies and url.startswith((settings.base_url + "/", NYT_BASE_URL + "/")):
        # Only NYT's own site gets the cookies, never static01.nyt.com or other hosts.
        headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in settings.cookies.items())
    params = {k: v for k, v in request.params.items() if v is not None}
    return {"url": url, "params": params, "headers": headers}


def _decode(request: Request, response: httpx.Response):
    """Return the decoded body, or raise the matching error."""
    logger.info("GET %s -> %s", response.request.url, response.status_code)
    status = response.status_code
    if status >= 400:
        message = f"HTTP {status} for {response.request.url}"
        if status == 429:
            raise NYTGamesRateLimitError(message, status_code=status, response=response,
                                         retry_after=retry_after(response))
        if status == 404:
            raise NYTGamesNotFoundError(request.not_found or message, status_code=status, response=response)
        if status in (401, 403):
            raise NYTGamesAuthenticationError(message, status_code=status, response=response)
        raise NYTGamesHTTPError(message, status_code=status, response=response)
    if request.kind == "text":
        return response.text
    try:
        return response.json()
    except ValueError:
        raise NYTGamesParseError(f"Expected JSON from {response.request.url}, got something else") from None


def run_sync(client: httpx.Client, settings: Settings, operation: Operation):
    """Run an operation with a sync httpx client and return its result.

    Errors from a request are thrown into the operation, so it can catch
    them (e.g. to stop at a 404).
    """
    try:
        request = next(operation)
        while True:
            try:
                response = _send_sync(client, settings, request)
            except NYTGamesHTTPError as error:
                request = operation.throw(error)
            else:
                request = operation.send(response)
    except StopIteration as stop:
        return stop.value


def _send_sync(client: httpx.Client, settings: Settings, request: Request):
    attempt = 0
    while True:
        response = None
        try:
            response = client.get(**_build(settings, request))
        except httpx.TransportError:
            if not _should_retry(settings, attempt, None):
                raise
        else:
            if not _should_retry(settings, attempt, response):
                return _decode(request, response)
        time.sleep(_delay(settings, attempt, response))
        attempt += 1


async def run_async(client: httpx.AsyncClient, settings: Settings, operation: Operation):
    """Run an operation with an async httpx client and return its result."""
    try:
        request = next(operation)
        while True:
            try:
                response = await _send_async(client, settings, request)
            except NYTGamesHTTPError as error:
                request = operation.throw(error)
            else:
                request = operation.send(response)
    except StopIteration as stop:
        return stop.value


async def _send_async(client: httpx.AsyncClient, settings: Settings, request: Request):
    attempt = 0
    while True:
        response = None
        try:
            response = await client.get(**_build(settings, request))
        except httpx.TransportError:
            if not _should_retry(settings, attempt, None):
                raise
        else:
            if not _should_retry(settings, attempt, response):
                return _decode(request, response)
        await asyncio.sleep(_delay(settings, attempt, response))
        attempt += 1

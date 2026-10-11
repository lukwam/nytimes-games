"""Requests for the sync and async clients.

Client operations are written once, as generators that yield `Request`s and
receive the decoded responses. `run_sync` drives one with a sync `get`
function and `run_async` with an async one, so both clients share every URL,
parser and error rule. Errors from a request are thrown into the operation,
so it can catch them (for example to stop at a 404).
"""
from collections.abc import Awaitable
from collections.abc import Callable
from collections.abc import Generator
from dataclasses import dataclass
from typing import Any

from nytgames.exceptions import NYTGamesAuthenticationError
from nytgames.exceptions import NYTGamesError
from nytgames.exceptions import NYTGamesHTTPError
from nytgames.exceptions import NYTGamesNotFoundError
from nytgames.exceptions import NYTGamesRateLimitError

RETRY_STATUSES = (429, 500, 502, 503, 504)


@dataclass
class Request:
    """One GET request to NYT, with the same arguments as the clients' `_get`.

    `path` is relative to the client's `base_url`, or a full URL.
    `json_response` returns the decoded JSON; otherwise the response itself
    (its `.content` is the body).
    """
    path: str
    params: dict | None = None
    json_response: bool = True


Operation = Generator[Request, Any, Any]


def retry_after(response) -> float | None:
    """Return the seconds from a Retry-After header, if it has a number."""
    try:
        return float(response.headers.get("Retry-After"))
    except (TypeError, ValueError):
        return None


def http_error(message: str, response) -> NYTGamesHTTPError:
    """Return the NYTGamesHTTPError subclass for a response's status code."""
    if response.status_code == 429:
        return NYTGamesRateLimitError(message, response=response, retry_after=retry_after(response))
    error_class = {
        401: NYTGamesAuthenticationError,
        403: NYTGamesAuthenticationError,
        404: NYTGamesNotFoundError,
    }.get(response.status_code, NYTGamesHTTPError)
    return error_class(message, response=response)


def run_sync(get: Callable[..., Any], operation: Operation):
    """Run an operation, sending each request with `get`, and return its result."""
    try:
        request = next(operation)
        while True:
            try:
                response = get(request.path, request.params, request.json_response)
            except NYTGamesError as error:
                request = operation.throw(error)
            else:
                request = operation.send(response)
    except StopIteration as stop:
        return stop.value


async def run_async(get: Callable[..., Awaitable[Any]], operation: Operation):
    """Run an operation, sending each request with an async `get`, and return its result."""
    try:
        request = next(operation)
        while True:
            try:
                response = await get(request.path, request.params, request.json_response)
            except NYTGamesError as error:
                request = operation.throw(error)
            else:
                request = operation.send(response)
    except StopIteration as stop:
        return stop.value

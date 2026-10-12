"""Fixtures for tests that run against both clients over mocked HTTP."""
import pytest

from tests.support import COOKIES
from tests.support import Api
from tests.support import nyt_mock


@pytest.fixture(params=["sync", "async"])
def make(request):
    """Make a sync or async client."""
    return lambda **kwargs: Api(request.param, **kwargs)


@pytest.fixture
def api(make):
    return make()


@pytest.fixture
def logged_in(make):
    return make(cookies=COOKIES)


@pytest.fixture
def mock():
    with nyt_mock() as router:
        yield router

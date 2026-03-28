"""Tests for fxrates package."""

import datetime

import httpx
import pytest
from pytest_httpx import HTTPXMock

from fxrates import get_rate, get_rates
from fxrates.client import get_rates as _get_rates_cached


@pytest.fixture(autouse=True)
def clear_cache():
    _get_rates_cached.cache_clear()
    yield
    _get_rates_cached.cache_clear()


DATE = datetime.date(2026, 1, 15)


def mock_rates(
    mock: HTTPXMock, base: str, quotes: tuple[str, ...], rates: dict[str, float]
) -> None:
    mock.add_response(
        url=f"https://api.frankfurter.app/2026-01-15?from={base}&to={','.join(quotes)}",
        json={"date": "2026-01-15", "rates": rates},
    )


# --- get_rate ---

def test_get_rate_returns_float(httpx_mock: HTTPXMock) -> None:
    mock_rates(httpx_mock, "USD", ("MXN",), {"MXN": 20.15})
    assert get_rate("USD", "MXN", DATE) == 20.15


def test_get_rate_same_currency_returns_one() -> None:
    assert get_rate("USD", "USD", DATE) == 1.0


def test_get_rate_case_insensitive(httpx_mock: HTTPXMock) -> None:
    mock_rates(httpx_mock, "USD", ("MXN",), {"MXN": 20.15})
    assert get_rate("usd", "mxn", DATE) == 20.15


def test_get_rate_returns_none_on_http_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=500)
    assert get_rate("USD", "MXN", DATE) is None


def test_get_rate_returns_none_on_network_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    assert get_rate("USD", "MXN", DATE) is None


# --- get_rates (batch) ---

def test_get_rates_returns_all_quotes(httpx_mock: HTTPXMock) -> None:
    mock_rates(httpx_mock, "USD", ("EUR", "MXN"), {"EUR": 0.92, "MXN": 20.15})
    rates = get_rates("USD", ("EUR", "MXN"), DATE)
    assert rates == {"EUR": 0.92, "MXN": 20.15}


def test_get_rates_returns_empty_dict_on_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=500)
    assert get_rates("USD", ("MXN",), DATE) == {}


# --- Caching ---

def test_get_rates_cached_on_second_call(httpx_mock: HTTPXMock) -> None:
    mock_rates(httpx_mock, "USD", ("MXN",), {"MXN": 20.15})
    get_rates("USD", ("MXN",), DATE)
    get_rates("USD", ("MXN",), DATE)  # should hit cache
    assert len(httpx_mock.get_requests()) == 1


def test_get_rates_caches_empty_dict_on_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=500)
    get_rates("USD", ("MXN",), DATE)
    result = get_rates("USD", ("MXN",), DATE)  # cache hit
    assert result == {}
    assert len(httpx_mock.get_requests()) == 1


def test_different_dates_make_separate_requests(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.frankfurter.app/2026-01-15?from=USD&to=MXN",
        json={"date": "2026-01-15", "rates": {"MXN": 20.15}},
    )
    httpx_mock.add_response(
        url="https://api.frankfurter.app/2026-01-16?from=USD&to=MXN",
        json={"date": "2026-01-16", "rates": {"MXN": 20.20}},
    )
    r1 = get_rate("USD", "MXN", datetime.date(2026, 1, 15))
    r2 = get_rate("USD", "MXN", datetime.date(2026, 1, 16))
    assert r1 == 20.15
    assert r2 == 20.20
    assert len(httpx_mock.get_requests()) == 2

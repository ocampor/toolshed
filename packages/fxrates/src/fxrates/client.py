"""Frankfurter API client for historical exchange rates."""

import datetime
import functools

import httpx

from fxrates.constants import BASE_URL


@functools.cache
def get_rates(
    base: str, quotes: tuple[str, ...], date: datetime.date
) -> dict[str, float]:
    """Fetch multiple quote rates for a single base/date in one API call.

    Results are cached in-memory for the session. Returns an empty dict on errors.
    Use this to minimize HTTP calls when several pairs share the same base and date.
    """
    try:
        resp = httpx.get(
            f"{BASE_URL}/{date}",
            params={"from": base.upper(), "to": ",".join(q.upper() for q in quotes)},
            timeout=10.0,
        )
        resp.raise_for_status()
        data: dict[str, dict[str, float]] = resp.json()
        return data.get("rates", {})
    except Exception:
        return {}


def get_rate(base: str, quote: str, date: datetime.date) -> float | None:
    """Return the exchange rate from base to quote on the given date.

    Returns 1.0 for same-currency pairs. Returns None if unavailable.
    Results are cached via get_rates.
    """
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return 1.0
    return get_rates(base, (quote,), date).get(quote)

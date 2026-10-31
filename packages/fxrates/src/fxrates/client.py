import datetime
import functools

import httpx

from fxrates.constants import BASE_URL


@functools.cache
def get_rates(
    base: str, quotes: tuple[str, ...], date: datetime.date
) -> dict[str, float]:
    """Cached in memory for the session; returns an empty dict on errors."""
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
    """Returns 1.0 for same-currency pairs and None when unavailable."""
    base, quote = base.upper(), quote.upper()
    if base == quote:
        return 1.0
    return get_rates(base, (quote,), date).get(quote)

# fxrates

Fetch historical currency exchange rates from [Frankfurter](https://www.frankfurter.app/) — free, no API key, ECB data.

## Install

```bash
pip install fxrates
```

## Quick start

```python
import datetime
from fxrates import get_rate, get_rates

# Single rate
rate = get_rate("USD", "MXN", datetime.date(2026, 1, 15))
# → 20.15

# Batch: multiple quotes for the same base/date in one API call
rates = get_rates("USD", ("MXN", "EUR"), datetime.date(2026, 1, 15))
# → {"MXN": 20.15, "EUR": 0.92}
```

## API

```python
get_rate(base, quote, date) -> float | None
```
Returns the exchange rate from `base` to `quote` on `date`. Returns `None` on network errors or unavailable pairs. Same currency returns `1.0`.

```python
get_rates(base, quotes, date) -> dict[str, float]
```
Fetches multiple quote currencies for the same base/date in a single HTTP request. Use this when you need several pairs for the same date to minimize API calls. Returns an empty dict on errors.

Both functions cache results in-memory for the session. Weekends and holidays are handled automatically by the API (returns the most recent available rate).

## Minimizing API calls

Group all needed pairs by `(date, base)` and call `get_rates` once per group:

```python
from fxrates import get_rates

# Instead of:
#   get_rate("USD", "MXN", date)   # 1 call
#   get_rate("USD", "EUR", date)   # 1 call  (same date+base — wasted!)

# Do:
rates = get_rates("USD", ("MXN", "EUR"), date)  # 1 call
tc1 = rates.get("MXN")
tc2 = rates.get("EUR")
```

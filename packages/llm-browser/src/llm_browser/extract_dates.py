"""Dates as pages print them, for a ``type: date`` extract field."""

import datetime

from llm_browser.extract_spec import ExtractSpec

# Without them dateparser fills a missing day or month from the run's date:
# "marzo 2026" would read as the 15th on the 15th.
REQUIRED_DATE_PARTS = ["day", "month"]


def parsed_date(
    text: str,
    spec: ExtractSpec,
    relative_base: datetime.datetime | None = None,
) -> datetime.date | None:
    """ISO first, so ``date_order`` never reorders it; with ``format`` only that
    strptime format. Relative dates resolve against the run's clock."""
    if spec.format:
        return strict_date(text, spec.format)
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        pass
    # Imported here: dateparser costs ~80 ms an import that reads no date skips.
    import dateparser

    settings: dict[str, object] = {
        "DATE_ORDER": spec.date_order,
        "REQUIRE_PARTS": REQUIRED_DATE_PARTS,
    }
    if relative_base is not None:
        settings["RELATIVE_BASE"] = relative_base
    parsed = dateparser.parse(text, languages=list(spec.languages), settings=settings)
    return parsed.date() if parsed else None


def strict_date(text: str, date_format: str) -> datetime.date | None:
    try:
        return datetime.datetime.strptime(text, date_format).date()
    except ValueError:
        return None

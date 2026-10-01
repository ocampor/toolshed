"""Dates as pages print them, for a ``type: date`` extract field."""

import datetime

import dateparser

from llm_browser.extract_spec import ExtractSpec


def parsed_date(text: str, spec: ExtractSpec) -> datetime.date | None:
    """ISO first, so ``date_order`` never reorders it; relative dates
    ("hace 3 semanas") resolve against the run's clock."""
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        pass
    parsed = dateparser.parse(
        text,
        languages=list(spec.languages),
        date_formats=[spec.format] if spec.format else None,
        settings={"DATE_ORDER": spec.date_order},
    )
    return parsed.date() if parsed else None

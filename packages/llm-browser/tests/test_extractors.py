"""Each extract `type` validates through the extractor registered for it."""

import datetime
import subprocess
import sys

import pytest
from pydantic import ValidationError

from llm_browser.extractors import (
    DateExtractor,
    Extractor,
    FloatExtractor,
    IntExtractor,
    StrExtractor,
    get_extractors,
)
from llm_browser.extract_dates import parsed_date
from llm_browser.extract_spec import ExtractSpec
from llm_browser.parse import ExtractField


@pytest.mark.parametrize(
    ("value_type", "extractor"),
    [
        ("str", StrExtractor),
        ("int", IntExtractor),
        ("float", FloatExtractor),
        ("date", DateExtractor),
    ],
)
def test_each_type_dispatches_to_its_extractor(
    value_type: str, extractor: type[Extractor]
) -> None:
    assert get_extractors().get(value_type) is extractor


def test_an_unregistered_type_fails_validation() -> None:
    with pytest.raises(ValidationError):
        ExtractField(type="bool")


@pytest.mark.parametrize(
    ("text", "languages", "expected"),
    [
        ("1 oct", ("en",), datetime.date(2026, 10, 1)),
        ("hace 3 semanas", ("es",), datetime.date(2026, 9, 24)),
        ("ayer", ("es",), datetime.date(2026, 10, 14)),
    ],
)
def test_relative_and_partial_dates_still_parse(
    text: str, languages: tuple[str, ...], expected: datetime.date
) -> None:
    spec = ExtractSpec(type="date", languages=languages)
    base = datetime.datetime(2026, 10, 15)

    assert parsed_date(text, spec, relative_base=base) == expected


def test_importing_the_extractors_does_not_load_dateparser() -> None:
    probe = "import sys, llm_browser.extractors; print('dateparser' in sys.modules)"
    loaded = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert loaded.stdout.strip() == "False"

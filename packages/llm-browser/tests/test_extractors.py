"""Each extract `type` validates through the extractor registered for it."""

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

"""Each extract ``type`` validates into its own spec, which converts the raw text."""

import datetime
import subprocess
import sys

import pytest
from pydantic import ValidationError

from llm_browser.extract_spec import (
    EXTRACT_SPEC,
    BaseSpec,
    DateSpec,
    DateTimeSpec,
    FloatSpec,
    IntSpec,
    StrSpec,
)
from llm_browser.explore_models import ExploreResult
from llm_browser.parse import ExtractField


@pytest.mark.parametrize(
    ("spec", "kind"),
    [
        ({}, StrSpec),
        ({"type": "str"}, StrSpec),
        ({"type": "int"}, IntSpec),
        ({"type": "float"}, FloatSpec),
        ({"type": "datetime"}, DateTimeSpec),
        ({"type": "date"}, DateSpec),
    ],
)
def test_each_type_validates_into_its_spec(
    spec: dict[str, str], kind: type[BaseSpec]
) -> None:
    assert type(EXTRACT_SPEC.validate_python(spec)) is kind


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "bool"},
        {"type": "int", "format": "%d"},
        {"type": "str", "languages": ["es"]},
    ],
)
def test_a_key_its_type_does_not_take_fails(spec: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EXTRACT_SPEC.validate_python(spec)


@pytest.mark.parametrize(
    ("text", "languages", "days_ago"),
    [("hace 3 semanas", ("es",), 21), ("ayer", ("es",), 1), ("yesterday", ("en",), 1)],
)
def test_relative_dates_resolve_against_today(
    text: str, languages: tuple[str, ...], days_ago: int
) -> None:
    spec = DateSpec(languages=languages)

    assert spec.value(text) == datetime.date.today() - datetime.timedelta(days=days_ago)


def test_an_unknown_language_fails_at_run_time() -> None:
    with pytest.raises(ValueError, match="Unknown language"):
        DateSpec(languages=("sp",)).value("1 oct 2026")


def test_importing_the_specs_does_not_load_dateparser() -> None:
    probe = "import sys, llm_browser.extract_spec; print('dateparser' in sys.modules)"
    loaded = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert loaded.stdout.strip() == "False"


def test_invalid_pattern_names_the_pattern() -> None:
    with pytest.raises(ValueError, match="invalid pattern '\\('"):
        ExtractField(pattern="(")


def test_explore_samples_keep_a_time_of_day() -> None:
    moment = datetime.datetime(2026, 10, 1, 14, 30)

    result = ExploreResult(
        count=1, sample=[{"t": moment}], empty_fields=[], text_chars=0
    )

    assert result.sample[0]["t"] == moment


@pytest.mark.parametrize(
    "date_format",
    ["%d/%m/%Y", "%d %b %Y", "%j %Y", "%Y-%m-%d %H:%M:%S.%f", "%d/%m/%Y %z"],
)
def test_a_whole_date_format_loads(date_format: str) -> None:
    assert ExtractField(type="datetime", format=date_format).spec.format == date_format

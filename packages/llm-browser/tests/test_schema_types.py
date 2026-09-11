"""Tests for the allowlisted YAML schema type parser."""

import datetime
import decimal
from pathlib import Path

import pytest
import yaml

from llm_browser.parse import build_model
from llm_browser.schema_types import resolve_type

SUPPORTED_TYPES = [
    ("str", str),
    ("int", int),
    ("float", float),
    ("bool", bool),
    ("Decimal", decimal.Decimal),
    ("date", datetime.date),
    ("datetime", datetime.datetime),
    ("str | None", str | None),
    ("int | None", int | None),
    ("Optional[int]", int | None),
    ("Optional[str]", str | None),
    ("int | str", int | str),
    ("list[str]", list[str]),
    ("list[int]", list[int]),
    ("dict[str, str]", dict[str, str]),
    ("dict[str, int]", dict[str, int]),
    ("list[str] | None", list[str] | None),
    ("Optional[list[str]]", list[str] | None),
    ("dict[str, list[int]]", dict[str, list[int]]),
    ("list[dict[str, str]]", list[dict[str, str]]),
]

REJECTED_TYPES = [
    "__import__('os').system('id')",
    "exec",
    "eval('1')",
    "os.system",
    "typing.List[str]",
    "print('hi')",
    "set[str]",
    "tuple[str, int]",
    "Any",
    "Unknown",
    "list[Unknown]",
    "dict[int, str]",
    "dict[str]",
    "list[str, int]",
    "str + int",
    "str &",
    "",
    "1",
    "lambda: 1",
]


@pytest.mark.parametrize(("type_str", "expected"), SUPPORTED_TYPES)
def test_resolve_type_supported_forms(type_str: str, expected: object) -> None:
    assert resolve_type(type_str) == expected


@pytest.mark.parametrize(("type_str", "expected"), SUPPORTED_TYPES)
def test_build_model_annotation_matches(
    tmp_path: Path, type_str: str, expected: object
) -> None:
    Model = build_model(_schema(tmp_path, type_str))
    assert Model.model_fields["value"].annotation == expected


@pytest.mark.parametrize("type_str", REJECTED_TYPES)
def test_resolve_type_rejects(type_str: str) -> None:
    with pytest.raises(ValueError, match="unsupported schema type"):
        resolve_type(type_str)


@pytest.mark.parametrize("type_str", REJECTED_TYPES)
def test_build_model_rejects(tmp_path: Path, type_str: str) -> None:
    with pytest.raises(ValueError, match="unsupported schema type"):
        build_model(_schema(tmp_path, type_str))


def test_a_rejected_type_string_never_executes(tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel"
    payload = f"__import__('pathlib').Path({str(sentinel)!r}).touch()"

    with pytest.raises(ValueError, match="unsupported schema type"):
        build_model(_schema(tmp_path, payload))

    assert not sentinel.exists()


def _schema(tmp_path: Path, type_str: str) -> Path:
    path = tmp_path / "schema.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "name": "Item",
                "fields": {"value": {"type": type_str, "child_selector": "td"}},
            }
        )
    )
    return path

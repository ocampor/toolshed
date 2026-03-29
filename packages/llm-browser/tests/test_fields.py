"""Tests for field type handlers and utils."""

from unittest.mock import MagicMock

import pytest

from llm_browser.fields import (
    execute_field,
    fill_checkbox,
    fill_select,
    fill_text,
)
from llm_browser.utils import field_selector, js_clear_field


@pytest.fixture
def page() -> MagicMock:
    return MagicMock()


# --- utils ---


def testfield_selector() -> None:
    el_id, selector = field_selector({"id": "myfield"})
    assert el_id == "myfield"
    assert selector == "#myfield"


def testfield_selector_numeric_id() -> None:
    el_id, selector = field_selector({"id": 123})
    assert el_id == "123"
    assert selector == "#123"


def testjs_clear_field(page: MagicMock) -> None:
    js_clear_field(page, "f1")
    page.evaluate.assert_called_once()
    args = page.evaluate.call_args
    assert args[0][1] == {"id": "f1", "focus": False}


def testjs_clear_field_with_focus(page: MagicMock) -> None:
    js_clear_field(page, "f1", focus=True)
    args = page.evaluate.call_args
    assert args[0][1] == {"id": "f1", "focus": True}


# --- fill_text ---


def test_fill_text_basic(page: MagicMock) -> None:
    fill_text(page, {"id": "f1", "value": "hello"})
    page.click.assert_called_once_with("#f1")
    page.fill.assert_called_once_with("#f1", "hello")


def test_fill_text_clear_first(page: MagicMock) -> None:
    fill_text(page, {"id": "f1", "value": "hello", "clear_first": True})
    page.evaluate.assert_called_once()  # JS clear
    page.fill.assert_called_once_with("#f1", "hello")


# --- fill_select ---


def test_fill_select(page: MagicMock) -> None:
    fill_select(page, {"id": "s1", "value": "02"})
    page.select_option.assert_called_once_with("#s1", "02")


# --- fill_checkbox ---


def test_fill_checkbox_needs_click(page: MagicMock) -> None:
    page.evaluate.return_value = False
    fill_checkbox(page, {"id": "c1", "checked": True, "ui_click": True})
    page.click.assert_called_once_with("#c1")


def test_fill_checkbox_already_checked(page: MagicMock) -> None:
    page.evaluate.return_value = True
    fill_checkbox(page, {"id": "c1", "checked": True, "ui_click": True})
    page.click.assert_not_called()


# --- execute_field ---


def test_execute_field_dispatches(page: MagicMock) -> None:
    execute_field(page, {"type": "text", "id": "f1", "value": "v"})
    page.click.assert_called_once_with("#f1")


def test_execute_field_unknown_type(page: MagicMock) -> None:
    with pytest.raises(ValueError, match="Unknown field type"):
        execute_field(page, {"type": "radio", "id": "r1"})

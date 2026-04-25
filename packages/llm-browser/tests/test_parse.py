"""Tests for the typed DOM-extraction API (ExtractField + ParseBase)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from pydantic import ValidationError

from llm_browser.parse import ExtractField, ParseBase, build_model
from llm_browser.session import BrowserSession


@pytest.fixture
def session(tmp_path: object) -> BrowserSession:
    s = BrowserSession(state_dir=tmp_path)  # type: ignore[arg-type]
    s._page = MagicMock()
    return s


def _two_row_locator(rows: list[dict[str, str]]) -> MagicMock:
    """Build a Playwright-locator mock that yields the given pre-extracted rows.

    Each ``rows`` entry is a dict mapping field name → text the child should
    return for ``textContent``. The mock returns one ``row`` element per dict;
    ``row.locator(child_selector).first.text_content()`` returns the value.
    """
    row_mocks = []
    for fields in rows:
        row = MagicMock()

        def _make_child_resolver(_fields: dict[str, str]) -> object:
            def _locator_for(child_sel: str) -> MagicMock:
                child = MagicMock()
                # Map "td.name" → "name" — we just take the substring after the
                # dot so test setups can be terse.
                key = child_sel.split(".", 1)[1]
                child.text_content.return_value = _fields.get(key)
                return child

            return _locator_for

        row.locator.side_effect = _make_child_resolver(fields)
        row_mocks.append(row)

    locator = MagicMock()
    locator.all.return_value = row_mocks
    return locator


# --- ExtractField as a default value ---


def test_extract_field_works_as_default_value() -> None:
    class User(ParseBase):
        name: str = ExtractField(child_selector="td.name")

    # The class is constructable: with valid data, no error.
    u = User(name="alice")
    assert u.name == "alice"
    # Field info is preserved on the model.
    info = User.model_fields["name"]
    assert isinstance(info, ExtractField)
    assert info.child_selector == "td.name"
    assert info.attribute == "textContent"


# --- extract_all happy path ---


def test_extract_all_returns_typed_instances(
    session: BrowserSession,
) -> None:
    class User(ParseBase):
        name: str = ExtractField(child_selector="td.name")

    locator = _two_row_locator([{"name": "Alice"}, {"name": "Bob"}])
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    users = User.extract_all(session, "tr.row")

    assert all(isinstance(u, User) for u in users)
    assert [u.name for u in users] == ["Alice", "Bob"]


# --- extract_all coerces types ---


def test_extract_all_coerces_types(session: BrowserSession) -> None:
    class Item(ParseBase):
        name: str = ExtractField(child_selector="td.name")
        price: int = ExtractField(child_selector="td.price")

    locator = _two_row_locator([{"name": "Widget", "price": "30"}])
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    items = Item.extract_all(session, "tr.row")

    assert items[0].price == 30
    assert isinstance(items[0].price, int)


# --- extract_all complains about plain fields ---


def test_extract_all_raises_on_plain_field(session: BrowserSession) -> None:
    class Bad(ParseBase):
        name: str = "default"  # no ExtractField

    locator = _two_row_locator([{"name": "Alice"}])
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    with pytest.raises(TypeError, match="not an ExtractField"):
        Bad.extract_all(session, "tr.row")


# --- extract_one ---


def test_extract_one_returns_first(session: BrowserSession) -> None:
    class User(ParseBase):
        name: str = ExtractField(child_selector="td.name")

    locator = _two_row_locator([{"name": "Alice"}, {"name": "Bob"}])
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    user = User.extract_one(session, "tr.row")
    assert user is not None
    assert user.name == "Alice"


def test_extract_one_returns_none_for_zero_rows(session: BrowserSession) -> None:
    class User(ParseBase):
        name: str = ExtractField(child_selector="td.name")

    locator = _two_row_locator([])
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    user = User.extract_one(session, "tr.row")
    assert user is None


# --- build_model (YAML schema route) ---


def _write_yaml(tmp_path: Path, contents: dict) -> Path:
    p = tmp_path / "schema.yaml"
    p.write_text(yaml.safe_dump(contents))
    return p


def test_build_model_simple_types(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        {
            "name": "Item",
            "fields": {
                "name": {"type": "str", "child_selector": "td.name"},
                "qty": {"type": "int", "child_selector": "td.qty"},
                "price": {"type": "float", "child_selector": "td.price"},
                "active": {"type": "bool", "child_selector": "td.active"},
            },
        },
    )
    Item = build_model(path)

    assert Item.__name__ == "Item"
    assert issubclass(Item, ParseBase)

    obj = Item(name="Widget", qty="3", price="9.99", active="true")
    assert obj.qty == 3
    assert obj.price == 9.99
    assert obj.active is True


def test_build_model_optional_with_default(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        {
            "name": "User",
            "fields": {
                "name": {"type": "str", "child_selector": "td.name"},
                "nickname": {
                    "type": "str | None",
                    "child_selector": "td.nick",
                    "default": None,
                },
            },
        },
    )
    User = build_model(path)
    u = User(name="Alice")
    assert u.nickname is None


def test_build_model_unknown_type_raises(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        {
            "name": "Bad",
            "fields": {"x": {"type": "Decimal", "child_selector": "td.x"}},
        },
    )
    with pytest.raises(NameError, match="Decimal"):
        build_model(path)


def test_build_model_required_field_no_default(tmp_path: Path) -> None:
    path = _write_yaml(
        tmp_path,
        {
            "name": "User",
            "fields": {"name": {"type": "str", "child_selector": "td.name"}},
        },
    )
    User = build_model(path)
    with pytest.raises(ValidationError):
        User()  # missing required `name`


def test_build_model_class_works_with_extract_all(
    tmp_path: Path, session: BrowserSession
) -> None:
    path = _write_yaml(
        tmp_path,
        {
            "name": "Repo",
            "fields": {
                "name": {"type": "str", "child_selector": "td.name"},
                "stars": {"type": "int", "child_selector": "td.stars"},
            },
        },
    )
    Repo = build_model(path)

    locator = _two_row_locator(
        [{"name": "foo", "stars": "42"}, {"name": "bar", "stars": "7"}]
    )
    session._page.locator.return_value = locator  # type: ignore[union-attr]

    repos = Repo.extract_all(session, "tr.row")
    assert len(repos) == 2
    assert all(isinstance(r, Repo) for r in repos)
    assert repos[0].name == "foo"
    assert repos[0].stars == 42
    assert isinstance(repos[0].stars, int)

# mypy: ignore-errors
# (FieldInfo is @final upstream; subclassing works in practice. Disabling mypy
# on this file rather than scattering type-ignore comments.)
"""Typed DOM extraction.

Define a Pydantic model whose fields use ``ExtractField`` as defaults, then
call ``Model.extract_all(session, selector)`` to get back instances with
values coerced by Pydantic::

    class User(ParseBase):
        name: str = ExtractField(child_selector="td.name")
        age:  int = ExtractField(child_selector="td.age")

    users = User.extract_all(session, "tr.row")     # list[User]
    first = User.extract_one(session, "tr.row")     # User | None

The YAML ``read`` action keeps using the same ``ExtractField`` underneath —
``ReadStep.extract`` accepts raw ``{child_selector, attribute}`` dicts and
coerces them through this class.
"""

import typing
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

from llm_browser.selectors import Selector


class ExtractField(FieldInfo):
    """A model field marked for HTML extraction.

    Use as a default value, like Pydantic's ``Field()``. ``child_selector``
    descends into a child of the matched row; if ``None``, the value is
    read off the row element itself. ``attribute`` is what to read —
    ``textContent`` (default), ``value``, or any HTML attribute name.
    """

    def __init__(
        self,
        *,
        child_selector: str | None = None,
        attribute: str = "textContent",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.child_selector = child_selector
        self.attribute = attribute


class ParseBase(BaseModel):
    """Pydantic model that can extract its instances from the DOM.

    Subclass and declare each field with ``ExtractField`` as its default::

        class User(ParseBase):
            name: str = ExtractField(child_selector="td.name")
            age:  int = ExtractField(child_selector="td.age")

        users = User.extract_all(session, "tr.row")
    """

    @classmethod
    def _spec(cls) -> dict[str, ExtractField]:
        spec: dict[str, ExtractField] = {}
        for name, info in cls.model_fields.items():
            if not isinstance(info, ExtractField):
                raise TypeError(
                    f"{cls.__name__}.{name}: not an ExtractField. "
                    f"Use `ExtractField(...)` as the default."
                )
            spec[name] = info
        return spec

    @classmethod
    def extract_all(cls, session, selector: Selector) -> list[Self]:
        rows = session.parse_elements(selector, cls._spec())
        return [cls.model_validate(row) for row in rows]

    @classmethod
    def extract_one(cls, session, selector: Selector) -> Self | None:
        rows = cls.extract_all(session, selector)
        return rows[0] if rows else None


def _resolve_type(type_str):
    """Turn a YAML type string into a real Python type.

    ``vars(typing)`` exposes Optional/Union/Annotated/List/Dict/...; ``eval``
    auto-loads Python builtins (int, str, bool, float, list, dict, tuple,
    set, ...). That covers the common cases without an allow-list. Schemas
    that need stdlib types beyond builtins should be written in Python.
    """
    return eval(type_str, vars(typing))


def build_model(yaml_path):
    """Load a YAML schema and return a Pydantic class equivalent to a
    hand-written ``ParseBase`` subclass.

    The returned class inherits ``ParseBase`` so ``extract_all`` and
    ``extract_one`` work without any extra wrapping::

        Repo = build_model("schemas/repo.yaml")
        repos = Repo.extract_all(session, "article.Box-row")

    Schema shape::

        name: Repo
        fields:
          name:
            type: str
            child_selector: "h3 a"
          stars:
            type: int
            child_selector: ".stars"
          description:
            type: str | None
            child_selector: ".desc"
            default: null            # required → omit; optional → must declare
    """
    raw = yaml.safe_load(Path(yaml_path).read_text())
    name = raw["name"]
    fields = {}
    for fname, fspec in raw["fields"].items():
        # Copy so we don't mutate the loaded YAML.
        spec = dict(fspec)
        type_str = spec.pop("type")
        py_type = _resolve_type(type_str)
        # Remaining keys (child_selector, attribute, default) flow to
        # ExtractField. FieldInfo recognises `default` natively; an absent
        # default leaves the field required (PydanticUndefined sentinel).
        ef = ExtractField(**spec)
        fields[fname] = (py_type, ef)
    return create_model(name, __base__=ParseBase, **fields)

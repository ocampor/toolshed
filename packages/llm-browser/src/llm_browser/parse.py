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
``ReadStep.extract`` accepts either the compact ``"td.name@href"`` string or a
raw ``{child_selector, attribute}`` mapping, both through
``ExtractField.coerce``.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import BaseModel, create_model
from pydantic.fields import FieldInfo

from llm_browser import constants, schema_types
from llm_browser.selectors import Selector


class ExtractField(FieldInfo):
    """A model field marked for HTML extraction.

    Use as a default value, like Pydantic's ``Field()``. ``child_selector``
    descends into a child of the matched row; if ``None``, the value is
    read off the row element itself. ``attribute`` is what to read —
    one of ``constants.EXTRACT_PROPERTIES`` (``textContent`` by default)
    or any HTML attribute name.
    """

    def __init__(
        self,
        *,
        child_selector: str | None = None,
        attribute: str = constants.DEFAULT_EXTRACT_ATTRIBUTE,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.child_selector = child_selector
        self.attribute = attribute

    @classmethod
    def parse(cls, spec: str) -> "ExtractField":
        """Read the compact ``"child selector@attribute"`` form.

        Every half is optional: ``"td.name"`` reads that child's text,
        ``"@href"`` reads the attribute off the row element itself,
        ``"td.name@href"`` does both, and ``""`` is the row's own text.
        """
        child_selector, separator, attribute = spec.rpartition(
            constants.EXTRACT_ATTRIBUTE_SEPARATOR
        )
        if not separator:
            child_selector, attribute = attribute, ""
        return cls(
            child_selector=child_selector or None,
            attribute=attribute or constants.DEFAULT_EXTRACT_ATTRIBUTE,
        )

    @classmethod
    def coerce(cls, spec: Any) -> "ExtractField":
        """One field from however a flow wrote it: compact string, mapping, or
        an already-built field. Anything else is a `ValueError`, so a flow that
        writes a list or a number fails validation rather than the run."""
        if isinstance(spec, ExtractField):
            return spec
        if isinstance(spec, str):
            return cls.parse(spec)
        if isinstance(spec, Mapping):
            try:
                return cls(**spec)
            except TypeError as exc:
                raise ValueError(f"invalid extract spec {spec!r}: {exc}") from exc
        raise ValueError(
            f"invalid extract spec {spec!r}: expected a string or a mapping"
        )


def parse_extract_spec(spec: Mapping[str, str] | None) -> dict[str, ExtractField]:
    """Turn ``{field: "child selector@attribute"}`` into extraction fields.

    ``None`` means "just the text", under the field name ``text``.
    """
    if spec is None:
        return {constants.DEFAULT_EXTRACT_FIELD: ExtractField()}
    return {name: ExtractField.coerce(value) for name, value in spec.items()}


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

    ``type`` strings are resolved by ``schema_types.resolve_type``, which
    accepts only the allowlisted names and container forms.
    """
    raw = yaml.safe_load(Path(yaml_path).read_text())
    name = raw["name"]
    fields = {}
    for fname, fspec in raw["fields"].items():
        # Copy so we don't mutate the loaded YAML.
        spec = dict(fspec)
        type_str = spec.pop("type")
        py_type = schema_types.resolve_type(type_str)
        # Remaining keys (child_selector, attribute, default) flow to
        # ExtractField. FieldInfo recognises `default` natively; an absent
        # default leaves the field required (PydanticUndefined sentinel).
        ef = ExtractField(**spec)
        fields[fname] = (py_type, ef)
    return create_model(name, __base__=ParseBase, **fields)

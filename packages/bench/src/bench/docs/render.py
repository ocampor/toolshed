import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

try:
    import griffe
    import griffe2md
except ImportError:
    # `from None`: a missing extra reads as one line, never a griffe traceback.
    raise ImportError("bench.docs needs the docs extra: install 'ocampor-bench[docs]'") from None

# A resolved constant longer than this is a path or a table, not a number.
DEFAULT_MAX_CHARS = 40

# griffe2md's defaults are written for a docs site with an index and full
# dotted paths. A model reads one document at a time, so: plain names as
# headings, no summary index, source order, signatures with their annotations,
# and inherited members left to the base class that declares them.
CONFIG: dict[str, Any] = {
    **griffe2md.default_config,
    "heading_level": 2,
    "show_root_heading": True,
    "show_root_full_path": False,
    "show_object_full_path": False,
    "show_root_members_full_path": False,
    "show_bases": True,
    "summary": False,
    "inherited_members": False,
    "members_order": "source",
    "show_signature_annotations": True,
    "separate_signature": True,
    # `model_config` is pydantic's own plumbing, not a field a flow writes.
    "filters": ["!^_", "!^model_config$"],
}

Members = Callable[[griffe.Module], list[str]]


class Document(NamedTuple):
    """A generated file: its heading, its opening line, and what it renders.

    ``prose`` is for a module or class whose *docstring* is the documentation
    and whose members are not. ``members`` is for the objects rendered whole,
    named outright or found by a callable at render time.
    """

    title: str
    intro: str
    members: tuple[str, ...] | Members = ()
    prose: tuple[tuple[str, str], ...] = ()
    config: dict[str, Any] = {}


def members_of(module: griffe.Module, document: Document) -> list[str]:
    if callable(document.members):
        return document.members(module)
    return list(document.members)


# A ClassVar, a property and a `self.x = x` are not keys a flow may write, but
# griffe2md renders every one of them as a field.
NOT_A_FIELD = frozenset({"property", "instance-attribute"})

# What `default_factory=<name>` produces, when a reader is better served by the
# value than by the call.
FACTORY_VALUES = {"list": "[]", "dict": "{}"}


def prune(module: griffe.Module, *, max_default_chars: int = DEFAULT_MAX_CHARS) -> None:
    """Drop from every class what a flow author cannot write.

    A pydantic model's ``ClassVar`` is configuration for the model, not a YAML
    key; an enum's class attributes are its members, so the rule applies to a
    model and nothing else.
    """
    for klass in classes_of(module):
        model = "pydantic-model" in klass.labels
        for name in list(klass.members):
            member = klass.members[name]
            config = model and "class-attribute" in member.labels
            if member.labels & NOT_A_FIELD or config:
                del klass.members[name]
            elif "pydantic-field" in member.labels:
                show_factory_default(member)  # type: ignore[arg-type]
                show_constant_default(module, member, max_default_chars)  # type: ignore[arg-type]


def show_constant_default(module: griffe.Module, field: griffe.Attribute, max_chars: int) -> None:
    """A default written as a constant renders as the name alone, so a reader
    cannot see that a wait's budget is shorter than its step's."""
    if not isinstance(field.value, griffe.ExprName):
        return
    path = field.value.canonical_path.removeprefix(f"{module.path}.")
    literal = getattr(module.get_member(path), "value", None) if path else None
    if literal is not None and len(str(literal)) <= max_chars:
        field.value = f"{field.value.name} (= {literal})"


def show_factory_default(field: griffe.Attribute) -> None:
    """``default_factory`` leaves no value, so the field reads as required."""
    constraints = field.extra.get("griffe_pydantic", {}).get("constraints", {})
    factory = constraints.get("default_factory")
    if factory is None or field.value is not None:
        return
    made = getattr(factory, "body", None) or FACTORY_VALUES.get(str(factory))
    field.value = str(made) if made is not None else f"{factory}()"


def classes_of(obj: griffe.Module | griffe.Class) -> list[griffe.Class]:
    found = []
    for member in obj.members.values():
        if member.is_alias:
            continue
        if member.is_module or member.is_class:
            found.extend(classes_of(member))  # type: ignore[arg-type]
        if member.is_class:
            found.append(member)  # type: ignore[arg-type]
    return found


def load_package(package: str, source: Path) -> griffe.Module:
    """The package as griffe reads it — statically, without importing it."""
    loaded = griffe.load(
        package,
        search_paths=[str(source)],
        extensions=griffe.load_extensions("griffe_pydantic"),
        resolve_aliases=True,
    )
    assert isinstance(loaded, griffe.Module)
    prune(loaded)
    return loaded


def prose_section(module: griffe.Module, heading: str, path: str) -> str:
    docstring = module[path].docstring
    return f"## {heading}\n\n{docstring.value if docstring else ''}\n"


MEMBER_HEADING = re.compile(r"^### `([^`]+)`", re.MULTILINE)


def render_member(module: griffe.Module, path: str, config: dict[str, Any] = CONFIG) -> str:
    """One object, its member headings qualified by the owner.

    A section is searched on its own, and eighteen sections all called
    `action` answer nothing.
    """
    obj = module[path]
    rendered = griffe2md.render_object_docs(obj, config)
    return MEMBER_HEADING.sub(rf"### `{obj.name}.\1`", rendered)


def render(module: griffe.Module, document: Document, header: str) -> str:
    config = {**CONFIG, **document.config}
    # Members first: the prose is background, and the models are the answer.
    bodies = [render_member(module, path, config) for path in members_of(module, document)] + [
        prose_section(module, heading, path) for heading, path in document.prose
    ]
    return "\n".join([header, f"# {document.title}\n", document.intro, "", *bodies])

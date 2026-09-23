"""The reference half of the docs, rendered from the source by griffe2md.

This module names *what* to document; griffe reads the signatures, docstrings
and ``Field(description=)`` out of the source statically, and griffe2md turns
them into markdown. The build hook (``hatch_build.py``) runs it, so
``docs/reference/*.md`` is a build artifact rather than a committed file.

Nothing here imports ``llm_browser``: the hook loads this file on its own, in
a build environment where the package is source, not an installed dependency.
"""

import griffe
from bench.docs.files import Reference
from bench.docs.render import CONFIG, Document, Members, members_of

HEADER = (
    "<!-- Generated from the source of `packages/llm-browser` in the toolshed "
    "repo; edit the docstrings, not this file. -->\n"
)

# The session methods for writing a step rather than running one. They answer a
# different question from the rest and are documented apart.
AUTHORING = (
    "explore",
    "explore_many",
    "survey",
    "count_of",
    "first_match",
    "verified_candidates",
)


def named(*paths: str) -> Members:
    return lambda module: list(paths)


def classes_named(where: str, suffix: str) -> Members:
    """Every class declared in ``where`` whose name ends in ``suffix``.

    By name rather than by list: a step type or selector form added to the
    models turns up in the docs without anyone remembering to add it here.
    An imported name is an alias, never a declaration, so it is skipped.
    """

    def found(module: griffe.Module) -> list[str]:
        classes = module[where].classes
        return [
            f"{where}.{name}"
            for name, member in classes.items()
            if name.endswith(suffix) and not member.is_alias
        ]

    return found


def step_models(module: griffe.Module) -> list[str]:
    extra = ["models.MatchFields", "models.SaveAs", "models.TargetSpec"]
    flow = ["models.Flow", "models.SubFlow", "models.Param", "models.FlowData"]
    return classes_named("models", "Step")(module) + extra + flow


def result_models(module: griffe.Module) -> list[str]:
    """The flow-level results, then every action result they are built from."""
    flow_level = [
        "models.FlowSuccess",
        "models.FlowError",
        "models.RetryHint",
        "models.SkippedStep",
        "models.MatchWarning",
    ]
    return flow_level + classes_named("results", "")(module)


DOCUMENTS: dict[str, Document] = {
    "reference/steps": Document(
        "Steps",
        "Every `action:` a flow can write, as the model that validates it. "
        "`BaseStep` holds the options every step takes; `SelectorStep` and "
        "`MatchFields` hold the ones every targeting step takes.",
        step_models,
    ),
    "reference/selectors": Document(
        "Selectors",
        "How a step names the element it acts on. A bare string is a CSS "
        "selector; these are the explicit spellings.",
        classes_named("selectors", "Selector"),
    ),
    "reference/waits": Document(
        "Wait states",
        "What `wait_for` waits for, and which states a `text:` wait accepts.",
        named(
            "models.WaitState",
            "models.WAIT_STATES",
            "models.TEXT_STATES",
            "models.check_text_state",
            "models.WaitForStep",
        ),
        (("How the wait polls", "waits"),),
    ),
    "reference/repeat": Document(
        "Repeating a step",
        "Running one step once per item of a list, or once per matched element.",
        named("repeat.Repeat", "repeat.RepeatBlock", "repeat.OnError"),
        (("The two forms", "repeat"),),
    ),
    "reference/behavior": Document(
        "Behavior",
        "The humanization knobs a run can be given, and the presets that set them.",
        named("behavior.Behavior", "behavior.Jitter", "behavior.profile"),
        (
            ("What humanization covers", "behavior"),
            ("Configuring it from YAML", "behavior_config"),
        ),
    ),
    "reference/results": Document(
        "Flow results",
        "What a run hands back, successful or not.",
        result_models,
    ),
    "reference/extract": Document(
        "Extract specs",
        "What a `read` step's `extract:` writes, one entry per column.",
        named("parse.ExtractField", "parse.ParseBase", "parse.build_model"),
        (("Types a schema may declare", "schema_types"),),
    ),
    "reference/session": Document(
        "BrowserSession",
        "The Python surface every flow step is built on; an embedding caller "
        "drives the same methods directly.",
        named(
            "session.BrowserSession",
            "models.PageProbe",
            "models.SessionResult",
            "models.SessionInfo",
            "html.SanitizeLevel",
        ),
        config={"filters": [*CONFIG["filters"], rf"!^({'|'.join(AUTHORING)})$"]},
    ),
    "reference/explore": Document(
        "Exploring before writing a step",
        "Counting and sampling what a selector matches, and reading what a "
        "page is made of — answers about the page, never a click.",
        named(
            "session.BrowserSession",
            "explore_models.ExploreTarget",
            "explore_models.ExploreResult",
            "explore_models.Intent",
            "survey_models.Survey",
        ),
        (("How a survey ranks what it finds", "survey"),),
        {"members": list(AUTHORING)},
    ),
    "reference/flows": Document(
        "Running a flow",
        "Loading a flow, handing it data and reading what comes back.",
        named(
            "flows.run_flow",
            "flows.load_flow_document",
            "flow_repository.FlowRepository",
            "selector_map.load_selector_map",
        ),
        (
            ("Data and templates", "flows"),
            ("Resolving a flow before it runs", "flow_pipeline"),
            ("Selector refs", "selector_map"),
        ),
    ),
    "reference/attach": Document(
        "Launched, attached and detached",
        "Which browser a command drives, and how long it lives.",
        prose=(("The CLI's browser lifecycle", "cli"),),
    ),
    "reference/drivers": Document(
        "Drivers",
        "Which backend to run against, and where each one falls short.",
        prose=(
            ("Picking a driver", "drivers"),
            ("The contract a driver implements", "drivers.base.Driver"),
            ("patchright", "drivers.patchright"),
            ("camoufox", "drivers.camoufox"),
            ("nodriver", "drivers.nodriver"),
            ("The Playwright family", "drivers.playwright_base"),
        ),
    ),
}


REFERENCE = Reference(package="llm_browser", header=HEADER, documents=DOCUMENTS)


def covered_modules(module: griffe.Module) -> set[str]:
    """Every module some document renders from, whole or through a member."""
    names = set()
    for document in DOCUMENTS.values():
        paths = [path for _, path in document.prose] + members_of(module, document)
        for path in paths:
            obj = module[path]
            parent = obj if obj.is_module else obj.parent
            assert parent is not None
            names.add(parent.path)
    return names

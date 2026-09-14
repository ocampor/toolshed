"""``llm-browser explore`` and ``llm-browser survey``: the two commands for
writing a step rather than running one.

Registered on the same group as the rest; they live here because they are the
only commands that read a targets file and rank what a page is made of.
"""

from pathlib import Path

import click
from click.core import ParameterSource
from pydantic import ValidationError

from llm_browser.cli_output import output
from llm_browser.constants import (
    DEFAULT_WAIT_TIMEOUT_MS,
    EXPLORE_MANY_MAX_TARGETS,
    EXPLORE_SAMPLE_CHARS,
    EXPLORE_SAMPLE_ROWS,
    SURVEY_MAX_ITEMS,
)
from llm_browser.explore_models import ExploreTarget, Intent, Verdict
from llm_browser.parse import parse_extract_spec
from llm_browser.session import BrowserSession


def extract_pairs(values: tuple[str, ...]) -> dict[str, str] | None:
    """``--extract name=child selector@attribute`` pairs; ``None`` when unused."""
    if not values:
        return None
    pairs: dict[str, str] = {}
    for value in values:
        name, separator, spec = value.partition("=")
        if not separator or not name:
            raise click.UsageError(f"--extract expects name=spec, got {value!r}.")
        if name in pairs:
            raise click.UsageError(f"--extract {name} given twice.")
        pairs[name] = spec
    return pairs


def load_targets(path: str) -> list[ExploreTarget]:
    """The `--targets` file: a YAML or JSON list of {selector, intent, extract}.

    A list with nothing in it would explore nothing and exit 0, which reads as
    "every selector is fine"; so would more targets than one page call takes.
    Both are usage errors here rather than a clean-looking answer.
    """
    import yaml as _yaml

    try:
        raw = _yaml.safe_load(Path(path).read_text())
    except _yaml.YAMLError as exc:
        raise click.UsageError(
            f"--targets is not readable YAML or JSON: {exc}"
        ) from exc
    if not isinstance(raw, list):
        raise click.UsageError("--targets expects a list of targets.")
    if not raw:
        raise click.UsageError("--targets is empty: nothing to explore.")
    if len(raw) > EXPLORE_MANY_MAX_TARGETS:
        raise click.UsageError(
            f"--targets takes at most {EXPLORE_MANY_MAX_TARGETS} targets in one "
            f"call, got {len(raw)}."
        )
    try:
        return [ExploreTarget.model_validate(target) for target in raw]
    except ValidationError as exc:
        raise click.UsageError(f"--targets has a bad entry: {exc}") from exc


@click.command()
@click.option("--selector", default=None, help="CSS, XPath, or ID selector.")
@click.option(
    "--targets",
    "targets_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="YAML/JSON file of CSS targets explored in one page call (max 20).",
)
@click.option(
    "--extract",
    "extract",
    multiple=True,
    metavar="NAME=SPEC",
    help="Field to read off each sampled row, as name=child selector@attribute. Repeatable.",
)
@click.option(
    "--sample",
    type=click.IntRange(min=0),
    default=EXPLORE_SAMPLE_ROWS,
    help="How many matches to read.",
)
@click.option(
    "--timeout",
    type=click.IntRange(min=0),
    default=DEFAULT_WAIT_TIMEOUT_MS,
    help="How long to wait for the first match (ms).",
)
@click.option(
    "--sample-chars",
    type=click.IntRange(min=0),
    default=EXPLORE_SAMPLE_CHARS,
    help="How much of each sampled field to keep.",
)
@click.option(
    "--intent",
    type=click.Choice([intent.value for intent in Intent]),
    default=Intent.READ.value,
    help="What the step will do with the selector; decides the verdict.",
)
@click.pass_context
def explore(
    ctx: click.Context,
    selector: str | None,
    targets_path: str | None,
    extract: tuple[str, ...],
    sample: int,
    timeout: int,
    sample_chars: int,
    intent: str,
) -> None:
    """Count and sample selectors before writing steps against them.

    `--selector` explores one; `--targets FILE` explores a page's worth in a
    single page call, answers in the order asked. Exits non-zero unless every
    verdict is `ok`, so a shell can tell a usable selector from an ambiguous,
    missing or unclickable one without parsing the JSON.

    A `--targets` entry is CSS the page can parse — no XPath, no selector-map
    alias — and one that is not gets that target's own `error: not css`.
    """
    if (selector is None) == (targets_path is None):
        raise click.UsageError("pass exactly one of --selector or --targets")
    if targets_path is not None:
        # A targets file carries an intent and an extract per entry, so a
        # flag meant for all of them would quietly mean nothing.
        for option in ("extract", "intent"):
            if ctx.get_parameter_source(option) is ParameterSource.COMMANDLINE:
                raise click.UsageError(f"--{option} is per target inside --targets")
    session: BrowserSession = ctx.obj["session"]
    if targets_path is not None:
        results = session.explore_many(
            load_targets(targets_path),
            sample=sample,
            sample_chars=sample_chars,
            timeout_ms=timeout,
        )
        output([result.model_dump(exclude_none=True) for result in results])
    else:
        assert selector is not None
        results = [
            session.explore(
                selector,
                extract=parse_extract_spec(extract_pairs(extract)),
                sample=sample,
                timeout_ms=timeout,
                intent=Intent(intent),
                sample_chars=sample_chars,
            )
        ]
        output(results[0])
    if any(result.verdict is not Verdict.OK for result in results):
        raise SystemExit(1)


@click.command()
@click.option(
    "--max-items",
    type=click.IntRange(min=1),
    default=SURVEY_MAX_ITEMS,
    help="How many named elements to report.",
)
@click.pass_context
def survey(ctx: click.Context, max_items: int) -> None:
    """Read what the page is made of before writing any selector.

    The named elements, the link families, the structures the page repeats and
    how long it has been up — one page call, no clicks and no scrolling.
    """
    session: BrowserSession = ctx.obj["session"]
    output(session.survey(max_items=max_items))

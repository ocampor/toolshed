"""CLI entry point for llm-browser.

Launched mode is single-process: ``patchright`` launches Chromium in-process
because that is where its stealth patches are injected, so ``open`` in one
shell command and ``screenshot`` in the next cannot work — the browser died
with the first Python process. Use ``run`` to launch, act and close in one
invocation, or the Python API.

Attach mode survives across invocations. ``attach`` answers the ``target_id``
of the tab it opened, and ``(--cdp-url, --target-id)`` is that tab's whole
address: no state file, so parallel callers each own their tab. ``run
--cdp-url`` does attach, run and release in one command. ``daemon`` spawns a
detached Chromium instead and ``stop`` kills it — but a daemon-spawned browser
is reached with ``connect_over_cdp``, which does not activate patchright's
patches; its value is a *warmed* profile reused across calls.

Every launch prints one Node ``DeprecationWarning`` (DEP0169) from
patchright's vendored HTTP bundle. It is harmless and upstream-tracked; do not
silence it with ``NODE_NO_WARNINGS=1``.
"""

import asyncio
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterator, NamedTuple, cast, get_args

import click
from yaml_engine.template import TemplatePathError, resolve_templates_in_dict
from pydantic import ValidationError
from pydantic_core import to_json

from llm_browser.behavior import Behavior
from llm_browser.cli_docs import docs
from llm_browser.cli_explore import explore, survey
from llm_browser.cli_output import output
from llm_browser.behavior_config import BehaviorConfigError, load_behavior
from llm_browser.constants import (
    DEFAULT_POLL_INTERVAL_MS,
    DEFAULT_SETTLE_MS,
    DEFAULT_WAIT_TIMEOUT_MS,
    DRIVER_ENV_VAR,
)
from llm_browser.flow_pipeline import resolve_flow, resolve_flow_text
from llm_browser.flow_repository import FileFlowRepository, FlowNotFoundError
from llm_browser.flow_passes import child_data, unindexed
from llm_browser.flows import load_flow_document, run_flow, with_flow_path
from llm_browser.html import SanitizeLevel
from llm_browser.models import (
    Flow,
    FlowData,
    FlowError,
    FlowResult,
    RunFlowStep,
    SubFlow,
    WaitState,
    check_settle_budget,
)
from llm_browser.results import BytesResult
from llm_browser.selector_map import (
    SelectorMap,
    load_selector_map,
    missing_selectors,
    selector_refs,
)
from llm_browser.session import BrowserSession


class CliFlow(NamedTuple):
    flow: Flow
    selector_map: SelectorMap | None
    missing: list[str]


def flow_with_selector_map(
    document: dict[str, Any], selector_map_path: str | None
) -> CliFlow:
    """A flow without refs never reads the map; a missing named map is a bad path, not an empty map."""
    flow = load_flow_document(document)
    refs = selector_refs(flow)
    if not refs:
        return CliFlow(flow, None, [])
    if selector_map_path is None:
        return CliFlow(flow, {}, refs)
    path = Path(selector_map_path)
    if not path.exists():
        raise ValueError(f"selector map not found: {selector_map_path}")
    selector_map = load_selector_map(path)
    return CliFlow(flow, selector_map, missing_selectors(flow, selector_map))


def fail_on_missing_selectors(label: str | None, missing: list[str]) -> None:
    if not missing:
        return
    click.echo(
        json.dumps(
            {
                "ok": False,
                "flow": label,
                "error": "MissingSelectorsError",
                "message": f"selector refs missing from the map: {', '.join(missing)}",
                "missing_selectors": missing,
            }
        ),
        err=True,
    )
    raise SystemExit(1)


@contextmanager
def budget_argument_errors() -> Iterator[None]:
    """A settle/timeout mismatch is a bad option pair: exit 2, like --interval 0."""
    try:
        yield
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc


@contextmanager
def url_argument_errors() -> Iterator[None]:
    """Exit 2 with a clean message, not a JSON line plus a traceback."""
    try:
        yield
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc


def prepare_output_path(path: str | Path) -> Path:
    """For a user-typed path; a flow's path goes through :func:`contained_output_path`."""
    out = Path(path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def contained_output_path(directory: Path, relative: str) -> Path:
    """``path:`` comes from ``--data`` and a download's name from the server, so both are untrusted."""
    root = directory.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise click.UsageError(
            f"refusing to write {relative!r} outside {root}: "
            "a step path is relative to the output directory"
        )
    return target


class _StructuredErrorGroup(click.Group):
    """Only unexpected exceptions get the JSON line; expected step failures return as ``ErrorResult``."""

    def invoke(self, ctx: click.Context) -> object:
        try:
            return super().invoke(ctx)
        except click.exceptions.ClickException:
            raise
        except (SystemExit, KeyboardInterrupt):
            raise
        except BaseException as exc:
            payload = {
                "command": ctx.invoked_subcommand or ctx.info_name,
                "error": type(exc).__name__,
                "message": str(exc).split("\n", 1)[0][:300],
            }
            click.echo(json.dumps(payload, ensure_ascii=False), err=True)
            if os.environ.get("LLM_BROWSER_QUIET") == "1":
                raise SystemExit(1) from exc
            raise


@click.group(cls=_StructuredErrorGroup)
@click.option(
    "--session",
    "session_id",
    default="default",
    help="Session ID for concurrent browsers.",
)
@click.option(
    "--driver",
    "driver_name",
    default=None,
    help="Driver name (patchright, camoufox, nodriver). Env: LLM_BROWSER_DRIVER.",
)
@click.option(
    "--behavior-config",
    "behavior_config",
    default=None,
    help=(
        "Path to a YAML humanization config. Empty file = human defaults "
        "on patchright. See llm_browser.behavior_config for the schema. "
        "When omitted, Behavior.off()."
    ),
)
@click.option(
    "--cdp-url",
    "cdp_url",
    default=None,
    help=(
        "Address a tab of a running Chromium instead of a state file. "
        "Pair with --target-id to reuse the tab a previous `attach` returned."
    ),
)
@click.option(
    "--target-id",
    "target_id",
    default=None,
    help="CDP target id of the tab to drive (from `attach`'s output).",
)
@click.pass_context
def main(
    ctx: click.Context,
    session_id: str,
    driver_name: str | None,
    behavior_config: str | None,
    cdp_url: str | None,
    target_id: str | None,
) -> None:
    """LLM-friendly browser automation with YAML flows."""
    ctx.ensure_object(dict)
    driver = driver_name or os.environ.get(DRIVER_ENV_VAR)
    behavior = None
    if behavior_config:
        try:
            behavior = load_behavior(behavior_config)
        except BehaviorConfigError as e:
            raise click.ClickException(str(e)) from e
    ctx.obj["cdp_url"] = cdp_url
    ctx.obj["target_id"] = target_id
    ctx.obj["session"] = build_session(
        session_id=session_id,
        driver=driver,
        behavior=behavior,
        cdp_url=cdp_url,
        target_id=target_id,
    )


def build_session(
    session_id: str,
    driver: str | None,
    behavior: Behavior | None,
    cdp_url: str | None,
    target_id: str | None,
) -> BrowserSession:
    """With ``--cdp-url`` the session is stateless and ``--target-id`` picks the tab."""
    if target_id and not cdp_url:
        raise click.UsageError("--target-id requires --cdp-url.")
    session = BrowserSession(
        session_id=session_id,
        driver=driver,
        behavior=behavior,
        stateless=bool(cdp_url),
    )
    if cdp_url and target_id:
        session.attach_to_tab(cdp_url, target_id)
    return session


@main.command()
@click.option("--url", required=True, help="URL to navigate to.")
@click.option("--headed/--headless", default=True, help="Run in headed mode.")
@click.pass_context
def open(ctx: click.Context, url: str, headed: bool) -> None:
    """Launch browser and navigate to URL."""
    session: BrowserSession = ctx.obj["session"]
    with url_argument_errors():
        result = session.launch(url=url, headed=headed)
    output(result)


@main.command()
@click.option(
    "--cdp-url",
    "cdp_url",
    default=None,
    help="CDP URL of a running Chromium (defaults to the group's --cdp-url).",
)
@click.pass_context
def attach(ctx: click.Context, cdp_url: str | None) -> None:
    """Attach to an already-running Chromium over CDP in a fresh tab.

    Outputs the new tab's ``target_id``; pass it back as
    ``--cdp-url ... --target-id ...`` to drive that same tab later.
    """
    session: BrowserSession = ctx.obj["session"]
    url = cdp_url or ctx.obj.get("cdp_url")
    if not url:
        raise click.UsageError("--cdp-url is required.")
    output(session.attach(url))


@main.command()
@click.option("--url", default=None, help="Optional URL to navigate to on spawn.")
@click.option("--headed/--headless", default=True, help="Run in headed mode.")
@click.option(
    "--executable",
    "executable",
    default=None,
    help="Path to your real Chrome/Chromium binary (defaults to patchright's bundled copy).",
)
@click.option(
    "--profile",
    "profile",
    default=None,
    help="Path to your real user-data-dir (defaults to the session's fresh profile). Close any running Chrome against this dir first.",
)
@click.pass_context
def daemon(
    ctx: click.Context,
    url: str | None,
    headed: bool,
    executable: str | None,
    profile: str | None,
) -> None:
    """Spawn a detached Chromium that survives this CLI invocation."""
    session: BrowserSession = ctx.obj["session"]
    with url_argument_errors():
        result = session.launch_detached(
            url=url, headed=headed, executable_path=executable, user_data_dir=profile
        )
    output(result)


@main.command()
@click.pass_context
def stop(ctx: click.Context) -> None:
    """Kill a detached Chromium started with `daemon`."""
    session: BrowserSession = ctx.obj["session"]
    result = session.stop_detached()
    output(result)


@main.command()
@click.option("--url", required=True, help="URL to navigate to.")
@click.pass_context
def goto(ctx: click.Context, url: str) -> None:
    """Navigate to a URL on the current session."""
    session: BrowserSession = ctx.obj["session"]
    with url_argument_errors():
        session.goto(url)
    output({"url": session.driver.page_url(session.get_page())})


@main.command()
@click.option(
    "--flow",
    "flow_path",
    default=None,
    help="Path to YAML flow file, or - to read the flow YAML from stdin.",
)
@click.option(
    "--flow-yaml",
    "flow_yaml",
    default=None,
    help="Flow YAML as a string, instead of --flow.",
)
@click.option("--data", "data_json", default="{}", help="JSON data for template vars.")
@click.option(
    "--selector-map",
    "selector_map_path",
    default=None,
    help="Path to selector_map.yaml for symbolic refs.",
)
@click.option(
    "--from",
    "from_step",
    default=None,
    help="Re-enter the flow at this step name; skip every step before it.",
)
@click.option(
    "--only",
    "only_specs",
    multiple=True,
    metavar="STEP=I,J",
    help=(
        "Run only these passes of a repeating step, by index. Repeatable, "
        "one --only per step; outputs keep the original indices."
    ),
)
@click.option(
    "--cdp-url",
    "cdp_url",
    default=None,
    help=(
        "Run one-shot against a running Chromium: attach over CDP in a fresh "
        "tab, run the flow, release the tab. State is never reused, so several "
        "invocations can run in parallel against the same browser."
    ),
)
@click.option(
    "--out-dir",
    "out_dir",
    default=".",
    help="Directory every step `path:` is written under. Default: the CWD.",
)
@click.option(
    "--capture-dir",
    "capture_dir",
    default=None,
    help="Where a failure's screenshot.png / dom.html land. Default: the session dir.",
)
@click.option(
    "--capture-level",
    "capture_level",
    type=click.Choice([level.value for level in SanitizeLevel]),
    default=SanitizeLevel.HIGH.value,
    help="How hard a failure's DOM snapshot is sanitized. Default: high.",
)
@click.option(
    "--behavior",
    "behavior_spec",
    default=None,
    help=(
        "Humanization for this run: human, off, or a path to a behavior YAML. "
        "Every step takes it unless it sets its own `humanize`. "
        "When omitted, the session's own behavior."
    ),
)
@click.pass_context
def run(
    ctx: click.Context,
    flow_path: str | None,
    flow_yaml: str | None,
    data_json: str,
    selector_map_path: str | None,
    from_step: str | None,
    only_specs: tuple[str, ...],
    cdp_url: str | None,
    out_dir: str,
    capture_dir: str | None,
    capture_level: str,
    behavior_spec: str | None,
) -> None:
    """Run a YAML flow top-to-bottom (or from --from <step> onward).

    Pass exactly one of --flow PATH (- for stdin) or --flow-yaml TEXT.

    The run itself writes nothing: every step result comes back in memory
    and this command is what puts it on disk. A step's `path:` is written
    under --out-dir; a screenshot or download without one lands there under
    its own name; a failure's captures go to --capture-dir.

    With --cdp-url the flow runs one-shot on an already-running Chromium:

        llm-browser run --cdp-url http://127.0.0.1:9223 \
            --flow flows/warm-site.yml --data '{"url":"https://en.wikipedia.org"}'
    """

    session: BrowserSession = ctx.obj["session"]
    session.capture_level = SanitizeLevel(capture_level)
    data = json.loads(data_json)
    document = asyncio.run(resolve_flow_options(flow_path, flow_yaml))
    flow, selector_map, missing = flow_with_selector_map(document, selector_map_path)
    fail_on_missing_selectors(flow_path or "<inline>", missing)
    behavior = resolve_behavior(behavior_spec)
    only = parse_only(only_specs)

    def execute(target: BrowserSession) -> object:
        result = run_cli_flow(
            target,
            flow,
            data,
            from_step=from_step,
            flow_path=file_path(flow_path),
            behavior=behavior,
            selector_map=selector_map,
            only=only,
        )
        return write_run(
            result,
            flow,
            data,
            out_dir=Path(out_dir),
            capture_dir=Path(capture_dir) if capture_dir else target.session_dir,
        )

    endpoint = cdp_url or ctx.obj.get("cdp_url")
    finished = cast(
        CliFlowRun,
        run_attached(session, endpoint, execute)
        if endpoint and not ctx.obj.get("target_id")
        else execute(session),
    )
    click.echo(json.dumps(finished.payload, ensure_ascii=False))
    if isinstance(finished.result, FlowError):
        raise SystemExit(1)


# The library keeps every output in memory; these are the only functions in
# the package that turn one into a file.


class CliFlowRun(NamedTuple):
    result: FlowResult
    payload: dict[str, Any]


def declared_paths(flow: Flow, data: dict[str, object]) -> dict[str, str]:
    """Keyed by the unresolved name, as ``run_loaded_flow`` keys ``outputs``;
    an unmapped ``ref:`` must not cost the run its files.
    """
    paths: dict[str, str] = {}
    flow_data = flow.validate_data(data)
    for step in flow.steps:
        if isinstance(step, RunFlowStep) and isinstance(step.flow, SubFlow):
            bindings = resolve_after_run(step.data, flow_data)
            paths.update(declared_paths(step.flow, child_data(flow_data, bindings)))
            continue
        path = getattr(step, "path", None)
        if path:
            named = resolve_after_run({"path": path}, flow_data)
            paths[step.qualified_name] = str(named["path"])
    return paths


def resolve_after_run(raw: dict[str, Any], data: FlowData) -> dict[str, Any]:
    """Pass items and ``save_as`` values are gone by now, so only keys reaching into them stay as written."""
    template_data = data.to_template_dict()
    resolved: dict[str, Any] = {}
    for key, value in raw.items():
        try:
            resolved[key] = resolve_templates_in_dict({key: value}, template_data)[key]
        except TemplatePathError:
            resolved[key] = value
    return resolved


def as_text(output: object) -> str:
    """``to_json``: python-mode rows carry ``Decimal``/``date`` objects ``json.dumps`` cannot encode."""
    if isinstance(output, str):
        return output
    return to_json(output).decode()


def write_outputs(
    outputs: dict[str, object], paths: dict[str, str], out_dir: Path
) -> dict[str, str]:
    """Bytes are always written; text and rows only where a ``path:`` asks."""
    targets = planned_outputs(outputs, paths, out_dir)
    for step, (target, payload) in targets.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, bytes):
            target.write_bytes(payload)
        else:
            target.write_text(payload)
    return {step: str(target) for step, (target, _) in targets.items()}


def planned_outputs(
    outputs: dict[str, object], paths: dict[str, str], out_dir: Path
) -> dict[str, tuple[Path, bytes | str]]:
    """Planned in full first, so a path escaping ``--out-dir`` fails with nothing on disk."""
    planned: dict[str, tuple[Path, bytes | str]] = {}
    for key, result in outputs.items():
        step, index = unindexed(key)
        path = paths.get(step)
        if isinstance(result, BytesResult):
            # The fallback name is the server's `Content-Disposition`
            # filename: take the basename, never its directories.
            name = path or Path(result.name).name
            planned[key] = (
                contained_output_path(out_dir, per_pass_path(name, index)),
                result.content,
            )
        elif path:
            planned[key] = (
                contained_output_path(out_dir, per_pass_path(path, index)),
                as_text(result),
            )
    return planned


def per_pass_path(path: str, index: int | None) -> str:
    """A repeated ``path:`` makes a file per pass, so the index lands in the name."""
    if index is None:
        return path
    name = PurePosixPath(path)
    return str(name.with_name(f"{name.stem}[{index}]{name.suffix}"))


def write_captures(error: FlowError, capture_dir: Path) -> dict[str, str]:
    written: dict[str, str] = {}
    if error.screenshot is not None:
        target = contained_output_path(capture_dir, "screenshot.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(error.screenshot)
        written["screenshot"] = str(target)
    if error.dom is not None:
        target = contained_output_path(capture_dir, "dom.html")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(error.dom)
        written["dom"] = str(target)
    return written


def describe_run(
    result: FlowResult, outputs: dict[str, str], captures: dict[str, str]
) -> dict[str, Any]:
    """``outputs`` and ``captures`` stay apart, or a step named ``screenshot`` takes the capture path."""
    payload: dict[str, Any] = result.model_dump(mode="json", exclude_none=True)
    payload["outputs"] = {**payload.get("outputs", {}), **outputs}
    return {**payload, **captures}


def write_run(
    result: FlowResult,
    flow: Flow,
    data: dict[str, object],
    out_dir: Path,
    capture_dir: Path,
) -> CliFlowRun:
    outputs = write_outputs(result.outputs, declared_paths(flow, data), out_dir)
    captures = (
        write_captures(result, capture_dir) if isinstance(result, FlowError) else {}
    )
    return CliFlowRun(result, describe_run(result, outputs, captures))


async def resolve_flow_options(
    flow_path: str | None, flow_yaml: str | None
) -> dict[str, Any]:
    """A file resolves `run-flow` refs against its own directory; inline text uses the CWD."""
    if (flow_path is None) == (flow_yaml is None):
        raise click.UsageError("pass exactly one of --flow or --flow-yaml")
    if flow_path == "":
        raise click.UsageError("--flow needs a path, or - for stdin")
    if flow_yaml is not None:
        return await resolve_flow_text(flow_yaml, FileFlowRepository(Path.cwd()))
    if flow_path == "-":
        stdin = click.get_text_stream("stdin").read()
        return await resolve_flow_text(stdin, FileFlowRepository(Path.cwd()))
    path = Path(str(flow_path))
    return await resolve_flow(path.name, FileFlowRepository(path.parent))


def file_path(flow_path: str | None) -> str | None:
    """``None`` for stdin and text sources, which have no file to retry from."""
    if flow_path is None or flow_path == "-":
        return None
    return str(Path(flow_path).resolve())


BEHAVIOR_PRESETS = {"human": Behavior.human, "off": Behavior.off}


def resolve_behavior(spec: str | None) -> Behavior | None:
    if spec is None:
        return None
    preset = BEHAVIOR_PRESETS.get(spec)
    if preset is not None:
        return preset()
    try:
        return load_behavior(spec)
    except (BehaviorConfigError, OSError) as e:
        raise click.ClickException(f"--behavior: {e}") from e


def parse_only(specs: tuple[str, ...]) -> dict[str, list[int]] | None:
    if not specs:
        return None
    only: dict[str, list[int]] = {}
    for spec in specs:
        name, _, indices = spec.partition("=")
        try:
            only[name] = [int(part) for part in indices.split(",") if part.strip()]
        except ValueError as exc:
            raise click.ClickException(f"--only {spec!r}: {exc}") from exc
        if not name or not only[name]:
            raise click.ClickException(f"--only {spec!r}: expected STEP=I,J")
    return only


def run_cli_flow(
    session: BrowserSession,
    flow: Flow,
    data: dict[str, object],
    *,
    from_step: str | None,
    flow_path: str | None = None,
    behavior: Behavior | None = None,
    selector_map: SelectorMap | None = None,
    only: dict[str, list[int]] | None = None,
) -> FlowResult:
    """``flow_path`` only fills ``retry_hint.flow_path``; the flow is already
    built."""
    result = run_flow(
        session,
        flow,
        data,
        from_step=from_step,
        behavior=behavior,
        selector_map=selector_map,
        only=only,
    )
    if flow_path is None:
        return result
    return with_flow_path(result, flow_path)


def run_attached(
    base: BrowserSession,
    cdp_url: str,
    execute: Callable[[BrowserSession], object],
) -> object:
    """Stateless; the uuid session id keeps concurrent runs out of each other's directories."""
    session = BrowserSession(
        session_id=f"{base.session_id}-{uuid.uuid4().hex[:8]}",
        state_dir=base.state_dir,
        driver=base.driver,
        behavior=base.behavior,
        capture=base.capture,
        capture_level=base.capture_level,
        executable_path=base.executable_path,
        stateless=True,
    )
    session.attach(cdp_url)
    try:
        return execute(session)
    finally:
        session.close()


def authored_subflows(document: dict[str, Any]) -> int:
    """Counted off the document, not the flow: an `action: repeat` block is a
    `run-flow` once loaded, but nobody wrote one."""
    steps = document.get("steps")
    if not isinstance(steps, list):
        return 0
    return sum(
        1 for s in steps if isinstance(s, dict) and s.get("action") == "run-flow"
    )


@main.command()
@click.option(
    "--flow",
    "flow_path",
    default=None,
    help="Path to YAML flow file, or - to read the flow YAML from stdin.",
)
@click.option(
    "--flow-yaml",
    "flow_yaml",
    default=None,
    help="Flow YAML as a string, instead of --flow.",
)
@click.option(
    "--selector-map",
    "selector_map_path",
    default=None,
    help="Path to selector_map.yaml for symbolic refs.",
)
def validate(
    flow_path: str | None,
    flow_yaml: str | None,
    selector_map_path: str | None,
) -> None:
    """Validate a YAML flow without launching a browser.

    Pass exactly one of --flow PATH (- for stdin) or --flow-yaml TEXT.

    Loads the flow + every referenced sub-flow and runs all model
    validators. Exits 0 with a JSON summary on success; exits 1 with a
    one-line JSON failure on any validation error, or on a ``ref:`` the
    ``--selector-map`` does not carry, whose ``missing_selectors`` names
    every such ref.

    Suitable for pre-commit hooks and CI — no browser session is
    created or used.
    """

    import yaml as _yaml

    label = "<inline>" if flow_path in (None, "-") else flow_path
    try:
        document = asyncio.run(resolve_flow_options(flow_path, flow_yaml))
        flow, _, missing = flow_with_selector_map(document, selector_map_path)
    except (
        ValidationError,
        FlowNotFoundError,
        _yaml.YAMLError,
        ValueError,
    ) as exc:
        click.echo(
            json.dumps(
                {
                    "ok": False,
                    "flow": label,
                    "error": type(exc).__name__,
                    "message": str(exc).split("\n", 1)[0][:500],
                }
            ),
            err=True,
        )
        raise SystemExit(1) from exc
    fail_on_missing_selectors(label, missing)
    output(
        {
            "ok": True,
            "flow": label,
            "step_count": len(flow.steps),
            "subflow_count": authored_subflows(document),
            "missing_selectors": missing,
        }
    )


@main.command()
@click.option(
    "--path",
    default=None,
    help="Destination PNG path; defaults to <session dir>/screenshot.png.",
)
@click.pass_context
def screenshot(ctx: click.Context, path: str | None) -> None:
    """Take a screenshot of the current page and write it out.

    The library hands back the PNG bytes; writing them is this command's job.
    """
    session: BrowserSession = ctx.obj["session"]
    content = session.screenshot_bytes()
    target = prepare_output_path(path or session.session_dir / "screenshot.png")
    target.write_bytes(content)
    output({"screenshot": str(target)})


def find_all_output(session: BrowserSession, selector: str) -> None:
    locator = session.find_all(selector)
    driver = session.driver
    count = driver.count(locator)
    items = [
        driver.evaluate(driver.nth(locator, i), "el => el.outerHTML")
        for i in range(count)
    ]
    output({"count": count, "items": items})


@main.command()
@click.option("--selector", required=True, help="CSS, XPath, or ID selector.")
@click.option("--all", "all_", is_flag=True, help="Return all matches as a JSON array.")
@click.pass_context
def find(ctx: click.Context, selector: str, all_: bool) -> None:
    """Find an element (or all matches with --all) and output outer HTML."""
    session: BrowserSession = ctx.obj["session"]
    if all_:
        find_all_output(session, selector)
        return
    element = session.find(selector)
    html: str = session.driver.evaluate(element, "el => el.outerHTML")
    output({"html": html})


@main.command("find-all")
@click.option("--selector", required=True, help="CSS, XPath, or ID selector.")
@click.pass_context
def find_all(ctx: click.Context, selector: str) -> None:
    """Find all matching elements and output their outer HTML (alias for `find --all`)."""
    session: BrowserSession = ctx.obj["session"]
    find_all_output(session, selector)


@main.command("wait-for")
@click.option("--selector", required=True, help="CSS, XPath, or ID selector.")
@click.option(
    "--state",
    type=click.Choice(get_args(WaitState)),
    default="attached",
    help="State to wait for.",
)
@click.option(
    "--timeout",
    type=click.IntRange(min=0),
    default=DEFAULT_WAIT_TIMEOUT_MS,
    help="Total budget (ms); 0 checks exactly once.",
)
@click.option(
    "--interval",
    type=click.IntRange(min=1),
    default=DEFAULT_POLL_INTERVAL_MS,
    help="Nominal gap between polls (ms); jittered, clamped to the budget.",
)
@click.option(
    "--settle",
    type=click.IntRange(min=1),
    default=DEFAULT_SETTLE_MS,
    help="For --state stable: how long the text must hold still (ms).",
)
@click.pass_context
def wait_for(
    ctx: click.Context,
    selector: str,
    state: str,
    timeout: int,
    interval: int,
    settle: int,
) -> None:
    """Poll until an element reaches a state; exit non-zero on timeout."""
    session: BrowserSession = ctx.obj["session"]
    with budget_argument_errors():
        check_settle_budget(cast(WaitState, state), settle, timeout)
    try:
        session.wait_for_element(
            selector,
            state=cast(WaitState, state),
            timeout=timeout,
            interval=interval,
            settle=settle,
        )
    except TimeoutError as exc:
        raise click.ClickException(str(exc)) from exc
    output({"selector": selector, "state": state})


@main.command("latest-tab")
@click.pass_context
def latest_tab(ctx: click.Context) -> None:
    """Switch to the most recently opened tab."""
    session: BrowserSession = ctx.obj["session"]
    page = session.latest_tab()
    output({"url": session.driver.page_url(page)})


@main.command()
@click.option("--selector", required=True, help="CSS, XPath, or ID selector.")
@click.option("--max-depth", default=0, help="Max nesting depth (0 = no limit).")
@click.option(
    "--level",
    type=click.Choice([level.value for level in SanitizeLevel]),
    default=SanitizeLevel.LOW.value,
    help="Sanitization aggressiveness.",
)
@click.pass_context
def dom(ctx: click.Context, selector: str, max_depth: int, level: str) -> None:
    """Output cleaned DOM snippet of an element."""
    session: BrowserSession = ctx.obj["session"]
    html = session.dom(selector, max_depth=max_depth, level=SanitizeLevel(level))
    output({"html": html})


main.add_command(docs)
main.add_command(explore)
main.add_command(survey)


@main.command()
@click.option("--selector", required=True, help="Download link/button selector.")
@click.option(
    "--path",
    default=None,
    help="Destination file path; defaults to the filename the server suggests.",
)
@click.pass_context
def download(ctx: click.Context, selector: str, path: str | None) -> None:
    """Download a file by clicking a link/button.

    The library hands back the bytes; writing them is this command's job.
    """
    session: BrowserSession = ctx.obj["session"]
    result = session.download_file(selector)
    target = prepare_output_path(path or result.name)
    target.write_bytes(result.content)
    output({"path": str(target), "name": result.name, "bytes": len(result.content)})


@main.command()
@click.pass_context
def close(ctx: click.Context) -> None:
    """Close the browser."""
    session: BrowserSession = ctx.obj["session"]
    result = session.close()
    output(result)


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Check browser status."""
    session: BrowserSession = ctx.obj["session"]
    result = session.status()
    output(result)

"""CLI entry point for llm-browser."""

import asyncio
import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, NamedTuple, cast, get_args

import click
from pydantic_core import to_json

from llm_browser.behavior import Behavior
from llm_browser.behavior_config import BehaviorConfigError, load_behavior
from llm_browser.constants import (
    DEFAULT_POLL_INTERVAL_MS,
    DEFAULT_SETTLE_MS,
    DEFAULT_WAIT_TIMEOUT_MS,
    DRIVER_ENV_VAR,
)
from llm_browser.flow_pipeline import resolve_flow, resolve_flow_text
from llm_browser.flow_repository import FileFlowRepository, FlowNotFoundError
from llm_browser.flows import load_flow_document, run_flow, with_flow_path
from llm_browser.html import SanitizeLevel
from llm_browser.models import (
    Flow,
    FlowError,
    FlowResult,
    RunFlowStep,
    SubFlow,
    WaitState,
    check_settle_budget,
)
from llm_browser.results import BytesResult
from llm_browser.selector_map import load_selector_map
from llm_browser.session import BrowserSession
from llm_browser.steps import resolve_step


@contextmanager
def budget_argument_errors() -> Iterator[None]:
    """A settle/timeout mismatch is a bad option pair: exit 2, like --interval 0."""
    try:
        yield
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc


@contextmanager
def url_argument_errors() -> Iterator[None]:
    """A rejected `--url` (non-http scheme) is a bad argument, so report it as
    one — a clean message and exit 2, not a JSON line plus a traceback."""
    try:
        yield
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc


def prepare_output_path(path: str | Path) -> Path:
    """The absolute path to write ``path`` to, with its parent created.

    A caller can name ``out/run_<ts>/turn.html`` without mkdir-ing first, and
    what is reported back reads the same from any working directory.

    For a path the *user* typed (``--path``). A path that came out of a flow
    goes through :func:`contained_output_path`, which will not leave its
    directory.

    Writing is the CLI's job alone; the library returns its output in memory.
    """
    out = Path(path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def contained_output_path(directory: Path, relative: str) -> Path:
    """Where ``relative`` lands under ``directory``, refusing to leave it.

    ``path:`` is templated from ``--data`` before it gets here and a
    download's filename is whatever the server called it, so both are
    untrusted: ``..`` segments and absolute paths would otherwise write
    wherever they pleased, and ``--out-dir`` promises they cannot.
    """
    root = directory.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise click.UsageError(
            f"refusing to write {relative!r} outside {root}: "
            "a step path is relative to the output directory"
        )
    return target


def _output(data: object) -> None:
    """Print JSON to stdout, then exit non-zero if the payload is a
    flow-level error. Supports Pydantic models and plain dicts.

    A ``FlowError`` represents an expected runtime failure (selector
    hidden, ambiguous, etc.) — surface it as a non-zero exit so
    callers can detect it without parsing JSON.
    """
    from pydantic import BaseModel

    from llm_browser.models import FlowError

    if isinstance(data, BaseModel):
        click.echo(data.model_dump_json(exclude_none=True))
    else:
        click.echo(json.dumps(data, ensure_ascii=False))
    if isinstance(data, FlowError):
        raise SystemExit(1)


class _StructuredErrorGroup(click.Group):
    """Click group that emits a one-line JSON summary for *unexpected*
    exceptions (programmer bugs, network failures) before re-raising.

    Expected runtime failures (Timeout/Value from action handlers) are
    returned as ``ErrorResult`` and never reach this fallback; this only
    catches things like assertion errors or driver crashes.
    """

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
    """Build the session every command runs against.

    With ``--cdp-url`` the session is stateless — no state.json is read or
    written — and ``--target-id`` addresses the exact tab to drive.
    """
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
    _output(result)


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
    _output(session.attach(url))


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
    _output(result)


@main.command()
@click.pass_context
def stop(ctx: click.Context) -> None:
    """Kill a detached Chromium started with `daemon`."""
    session: BrowserSession = ctx.obj["session"]
    result = session.stop_detached()
    _output(result)


@main.command()
@click.option("--url", required=True, help="URL to navigate to.")
@click.pass_context
def goto(ctx: click.Context, url: str) -> None:
    """Navigate to a URL on the current session."""
    session: BrowserSession = ctx.obj["session"]
    with url_argument_errors():
        session.goto(url)
    _output({"url": session.driver.page_url(session.get_page())})


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
@click.pass_context
def run(
    ctx: click.Context,
    flow_path: str | None,
    flow_yaml: str | None,
    data_json: str,
    selector_map_path: str | None,
    from_step: str | None,
    cdp_url: str | None,
    out_dir: str,
    capture_dir: str | None,
    capture_level: str,
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
    selector_map = (
        load_selector_map(Path(selector_map_path))
        if selector_map_path and Path(selector_map_path).exists()
        else None
    )
    data = json.loads(data_json)
    document = asyncio.run(resolve_flow_options(flow_path, flow_yaml))
    flow = load_flow_document(document, selector_map=selector_map)

    def execute(target: BrowserSession) -> object:
        result = run_cli_flow(
            target, flow, data, from_step=from_step, flow_path=file_path(flow_path)
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


# --- Writing what a run returned ---
#
# The library keeps every output in memory; these are the only functions in
# the package that turn one into a file.


class CliFlowRun(NamedTuple):
    result: FlowResult
    payload: dict[str, Any]


def declared_paths(flow: Flow, data: dict[str, object]) -> dict[str, str]:
    """Qualified step name to the ``path:`` that step asked the CLI to write.

    The value comes from the resolved step, so ``path: out/{{ id }}.png``
    names the file the flow meant. The *key* comes from the unresolved one,
    because that is what ``run_loaded_flow`` keys ``outputs`` on — a step
    whose ``name:`` is itself templated would otherwise never match its own
    output, and its file would silently not be written.
    """
    paths: dict[str, str] = {}
    flow_data = flow.validate_data(data)
    for step in flow.steps:
        resolved = resolve_step(step, flow_data)
        if isinstance(resolved, RunFlowStep) and isinstance(resolved.flow, SubFlow):
            paths.update(declared_paths(resolved.flow, resolved.data))
            continue
        path = getattr(resolved, "path", None)
        if path:
            paths[step.qualified_name] = str(path)
    return paths


def as_text(output: object) -> str:
    """A non-bytes output as the file a ``path:`` asks for: ``dom`` text
    verbatim, ``read`` / ``parse`` rows as JSON.

    ``to_json`` rather than ``json.dumps``: a ``parse`` schema may declare
    ``Decimal``, ``date`` or ``datetime``, and rows reach here in python mode
    carrying the real objects. ``json.dumps`` cannot encode any of them, and
    the resulting ``TypeError`` would replace the flow result with a
    traceback.
    """
    if isinstance(output, str):
        return output
    return to_json(output).decode()


def write_outputs(
    outputs: dict[str, object], paths: dict[str, str], out_dir: Path
) -> dict[str, str]:
    """Write the run's outputs, returning step name to file written.

    Bytes are always written — a PNG on stdout helps nobody — under the
    step's ``path:`` or, failing that, the name the payload came with.
    Text and rows are written only where the step asked for a file; they
    stay in the JSON either way.
    """
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
    """Every file this run is about to write, resolved and bounds-checked.

    Planned in full before anything is written so that a path trying to leave
    ``--out-dir`` fails the command with nothing on disk, rather than half a
    run's output and an error.
    """
    planned: dict[str, tuple[Path, bytes | str]] = {}
    for step, output in outputs.items():
        path = paths.get(step)
        if isinstance(output, BytesResult):
            # The fallback name is the server's `Content-Disposition`
            # filename: take the basename, never its directories.
            target = contained_output_path(out_dir, path or Path(output.name).name)
            planned[step] = (target, output.content)
        elif path:
            planned[step] = (contained_output_path(out_dir, path), as_text(output))
    return planned


def write_captures(error: FlowError, capture_dir: Path) -> dict[str, str]:
    """Write the failing page's screenshot and DOM, returning what was written."""
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
    """The JSON this command prints: every payload the CLI put on disk is
    reported as its path rather than as base64.

    ``outputs`` is keyed by step and ``captures`` by ``screenshot`` / ``dom``,
    which is why they stay apart — a step named ``screenshot`` would otherwise
    take the failing page's capture path as its own output.
    """
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
    """The one place the CLI turns its options into a resolved flow document.

    A file resolves its `run-flow` refs against its own directory; inline text
    has no directory of its own, so it uses the CWD.
    """
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


def run_cli_flow(
    session: BrowserSession,
    flow: Flow,
    data: dict[str, object],
    *,
    from_step: str | None,
    flow_path: str | None = None,
) -> FlowResult:
    """``flow_path`` only fills ``retry_hint.flow_path``; the flow is already
    built."""
    result = run_flow(session, flow, data, from_step=from_step)
    if flow_path is None:
        return result
    return with_flow_path(result, flow_path)


def run_attached(
    base: BrowserSession,
    cdp_url: str,
    execute: Callable[[BrowserSession], object],
) -> object:
    """Attach to ``cdp_url`` in a stateless session, run ``execute``, close.

    Nothing is persisted, so a previous invocation's state is never reused
    and parallel runs against the same Chromium each own their tab, addressed
    by its CDP target id. Closing an attached session releases only that tab.

    The session id carries a uuid suffix so concurrent runs never share a
    session directory (screenshots, DOM dumps) with each other or with the
    caller's own session.
    """
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

    Loads the flow + every referenced sub-flow, expands selector-map
    refs, and runs all model validators. Exits 0 with a JSON summary
    on success; exits 1 with a one-line JSON failure on any validation
    error.

    Suitable for pre-commit hooks and CI — no browser session is
    created or used.
    """

    import yaml as _yaml
    from pydantic import ValidationError

    label = "<inline>" if flow_path in (None, "-") else flow_path
    try:
        selector_map = (
            load_selector_map(Path(selector_map_path))
            if selector_map_path and Path(selector_map_path).exists()
            else None
        )
        document = asyncio.run(resolve_flow_options(flow_path, flow_yaml))
        flow = load_flow_document(document, selector_map=selector_map)
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
    subflow_count = sum(1 for s in flow.steps if isinstance(s, RunFlowStep))
    _output(
        {
            "ok": True,
            "flow": label,
            "step_count": len(flow.steps),
            "subflow_count": subflow_count,
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
    _output({"screenshot": str(target)})


def _find_all_output(session: BrowserSession, selector: str) -> None:
    locator = session.find_all(selector)
    driver = session.driver
    count = driver.count(locator)
    items = [
        driver.evaluate(driver.nth(locator, i), "el => el.outerHTML")
        for i in range(count)
    ]
    _output({"count": count, "items": items})


@main.command()
@click.option("--selector", required=True, help="CSS, XPath, or ID selector.")
@click.option("--all", "all_", is_flag=True, help="Return all matches as a JSON array.")
@click.pass_context
def find(ctx: click.Context, selector: str, all_: bool) -> None:
    """Find an element (or all matches with --all) and output outer HTML."""
    session: BrowserSession = ctx.obj["session"]
    if all_:
        _find_all_output(session, selector)
        return
    element = session.find(selector)
    html: str = session.driver.evaluate(element, "el => el.outerHTML")
    _output({"html": html})


@main.command("find-all")
@click.option("--selector", required=True, help="CSS, XPath, or ID selector.")
@click.pass_context
def find_all(ctx: click.Context, selector: str) -> None:
    """Find all matching elements and output their outer HTML (alias for `find --all`)."""
    session: BrowserSession = ctx.obj["session"]
    _find_all_output(session, selector)


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
    _output({"selector": selector, "state": state})


@main.command("latest-tab")
@click.pass_context
def latest_tab(ctx: click.Context) -> None:
    """Switch to the most recently opened tab."""
    session: BrowserSession = ctx.obj["session"]
    page = session.latest_tab()
    _output({"url": session.driver.page_url(page)})


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
    _output({"html": html})


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
    _output({"path": str(target), "name": result.name, "bytes": len(result.content)})


@main.command()
@click.pass_context
def close(ctx: click.Context) -> None:
    """Close the browser."""
    session: BrowserSession = ctx.obj["session"]
    result = session.close()
    _output(result)


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Check browser status."""
    session: BrowserSession = ctx.obj["session"]
    result = session.status()
    _output(result)

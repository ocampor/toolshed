"""CLI entry point for llm-browser."""

import json
import os

import click

from llm_browser.actions import ErrorResult
from llm_browser.behavior_config import BehaviorConfigError, load_behavior
from llm_browser.constants import DRIVER_ENV_VAR
from llm_browser.flows import FlowRunner
from llm_browser.models import FlowResult
from llm_browser.session import BrowserSession


def _output(data: object) -> None:
    """Print JSON to stdout, then exit non-zero if the payload is a
    flow-level error. Supports Pydantic models and plain dicts.

    A FlowResult whose ``data`` is an ``ErrorResult`` represents an expected
    runtime failure (selector hidden, ambiguous, etc.) — surface it as a
    non-zero exit so callers can detect it without parsing JSON.
    """
    from pydantic import BaseModel

    if isinstance(data, BaseModel):
        click.echo(data.model_dump_json(exclude_none=True))
    else:
        click.echo(json.dumps(data, ensure_ascii=False))
    if isinstance(data, FlowResult) and isinstance(data.data, ErrorResult):
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
@click.pass_context
def main(
    ctx: click.Context,
    session_id: str,
    driver_name: str | None,
    behavior_config: str | None,
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
    ctx.obj["session"] = BrowserSession(
        session_id=session_id, driver=driver, behavior=behavior
    )


@main.command()
@click.option("--url", required=True, help="URL to navigate to.")
@click.option("--headed/--headless", default=True, help="Run in headed mode.")
@click.pass_context
def open(ctx: click.Context, url: str, headed: bool) -> None:
    """Launch browser and navigate to URL."""
    session: BrowserSession = ctx.obj["session"]
    result = session.launch(url=url, headed=headed)
    _output(result)


@main.command()
@click.option("--cdp-url", required=True, help="CDP URL of a running Chromium.")
@click.pass_context
def attach(ctx: click.Context, cdp_url: str) -> None:
    """Attach to an already-running Chromium over CDP."""
    session: BrowserSession = ctx.obj["session"]
    result = session.attach(cdp_url)
    _output(result)


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
    session.goto(url)
    _output({"url": session.driver.page_url(session.get_page())})


@main.command()
@click.option("--flow", "flow_path", required=True, help="Path to YAML flow file.")
@click.option("--data", "data_json", default="{}", help="JSON data for template vars.")
@click.option(
    "--selector-map",
    "selector_map_path",
    default=None,
    help="Path to selector_map.yaml for symbolic refs.",
)
@click.pass_context
def run(
    ctx: click.Context, flow_path: str, data_json: str, selector_map_path: str | None
) -> None:
    """Run a YAML flow. Pauses at first checkpoint."""
    from pathlib import Path

    session: BrowserSession = ctx.obj["session"]
    map_path = Path(selector_map_path) if selector_map_path else None
    runner = FlowRunner(session, selector_map_path=map_path)
    data = json.loads(data_json)
    result = runner.run(flow_path, data)
    _output(result)


@main.command()
@click.option(
    "--data", "data_json", default="{}", help="JSON data to merge before resuming."
)
@click.option(
    "--selector-map",
    "selector_map_path",
    default=None,
    help="Path to selector_map.yaml for symbolic refs.",
)
@click.pass_context
def resume(ctx: click.Context, data_json: str, selector_map_path: str | None) -> None:
    """Resume a paused flow from the last checkpoint."""
    from pathlib import Path

    session: BrowserSession = ctx.obj["session"]
    map_path = Path(selector_map_path) if selector_map_path else None
    runner = FlowRunner(session, selector_map_path=map_path)
    data = json.loads(data_json) if data_json != "{}" else None
    result = runner.resume(data)
    _output(result)


@main.command()
@click.pass_context
def screenshot(ctx: click.Context) -> None:
    """Take a screenshot of the current page."""
    session: BrowserSession = ctx.obj["session"]
    path = session.take_screenshot()
    _output({"screenshot": str(path)})


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
@click.pass_context
def dom(ctx: click.Context, selector: str, max_depth: int) -> None:
    """Output cleaned DOM snippet of an element."""
    session: BrowserSession = ctx.obj["session"]
    html = session.dom(selector, max_depth=max_depth)
    _output({"html": html})


@main.command()
@click.option("--selector", required=True, help="Download link/button selector.")
@click.option("--path", required=True, help="Destination file path.")
@click.pass_context
def download(ctx: click.Context, selector: str, path: str) -> None:
    """Download a file by clicking a link/button."""
    session: BrowserSession = ctx.obj["session"]
    result = session.download_file(selector, path)
    _output({"path": str(result)})


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

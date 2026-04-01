"""CLI entry point for llm-browser."""

import json

import click

from llm_browser.flows import FlowRunner
from llm_browser.session import BrowserSession


def _output(data: object) -> None:
    """Print JSON to stdout. Supports Pydantic models and plain dicts."""
    from pydantic import BaseModel

    if isinstance(data, BaseModel):
        click.echo(data.model_dump_json(exclude_none=True))
    else:
        click.echo(json.dumps(data, ensure_ascii=False))


@click.group()
@click.option(
    "--session",
    "session_id",
    default="default",
    help="Session ID for concurrent browsers.",
)
@click.pass_context
def main(ctx: click.Context, session_id: str) -> None:
    """LLM-friendly browser automation with YAML flows."""
    ctx.ensure_object(dict)
    ctx.obj["session"] = BrowserSession(session_id=session_id)


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
@click.option("--url", required=True, help="URL to navigate to.")
@click.pass_context
def goto(ctx: click.Context, url: str) -> None:
    """Navigate to a URL on the current session."""
    session: BrowserSession = ctx.obj["session"]
    session.goto(url)
    _output({"url": session.get_page().url})


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


@main.command()
@click.option("--selector", required=True, help="CSS, XPath, or ID selector.")
@click.pass_context
def find(ctx: click.Context, selector: str) -> None:
    """Find a single element and output its outer HTML."""
    session: BrowserSession = ctx.obj["session"]
    element = session.find(selector)
    html: str = element.evaluate("el => el.outerHTML")
    _output({"html": html})


@main.command("find-all")
@click.option("--selector", required=True, help="CSS, XPath, or ID selector.")
@click.pass_context
def find_all(ctx: click.Context, selector: str) -> None:
    """Find all matching elements and output their outer HTML."""
    session: BrowserSession = ctx.obj["session"]
    locator = session.find_all(selector)
    count = locator.count()
    items = [locator.nth(i).evaluate("el => el.outerHTML") for i in range(count)]
    _output({"count": count, "items": items})


@main.command("latest-tab")
@click.pass_context
def latest_tab(ctx: click.Context) -> None:
    """Switch to the most recently opened tab."""
    session: BrowserSession = ctx.obj["session"]
    page = session.latest_tab()
    _output({"url": page.url})


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

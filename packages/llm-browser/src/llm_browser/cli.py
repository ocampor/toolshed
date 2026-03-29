"""CLI entry point for llm-browser."""

import json

import click

from llm_browser.actions import execute_action
from llm_browser.flows import FlowRunner
from llm_browser.models import Step
from llm_browser.scripts import load_js
from llm_browser.session import BrowserSession


def _output(data: object) -> None:
    """Print JSON to stdout. Supports Pydantic models and plain dicts."""
    from pydantic import BaseModel

    if isinstance(data, BaseModel):
        click.echo(data.model_dump_json(exclude_none=True))
    else:
        click.echo(json.dumps(data, ensure_ascii=False))


@click.group()
@click.option("--session", "session_id", default="default", help="Session ID for concurrent browsers.")
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
@click.option("--flow", "flow_path", required=True, help="Path to YAML flow file.")
@click.option("--data", "data_json", default="{}", help="JSON data for template vars.")
@click.pass_context
def run(ctx: click.Context, flow_path: str, data_json: str) -> None:
    """Run a YAML flow. Pauses at first checkpoint."""
    session: BrowserSession = ctx.obj["session"]
    runner = FlowRunner(session)
    data = json.loads(data_json)
    result = runner.run(flow_path, data)
    _output(result)


@main.command()
@click.option("--data", "data_json", default="{}", help="JSON data to merge before resuming.")
@click.pass_context
def resume(ctx: click.Context, data_json: str) -> None:
    """Resume a paused flow from the last checkpoint."""
    session: BrowserSession = ctx.obj["session"]
    runner = FlowRunner(session)
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


@main.command("eval")
@click.option("--js", required=True, help="JavaScript to evaluate.")
@click.pass_context
def eval_cmd(ctx: click.Context, js: str) -> None:
    """Evaluate JavaScript on the current page."""
    session: BrowserSession = ctx.obj["session"]
    result = session.evaluate_js(js)
    _output({"result": result})


@main.command("read-form")
@click.option("--selector", default="input[type=text], input:not([type])", help="CSS selector.")
@click.pass_context
def read_form(ctx: click.Context, selector: str) -> None:
    """Read all form field values matching a selector."""
    session: BrowserSession = ctx.obj["session"]
    page = session.get_page()
    result = page.evaluate(load_js("read_form"), selector)
    _output({"fields": result})


@main.command("dismiss-modal")
@click.option("--selector", default=".modal.fade.in, .modal.show", help="Modal CSS selector.")
@click.pass_context
def dismiss_modal(ctx: click.Context, selector: str) -> None:
    """Dismiss a modal dialog if present."""
    session: BrowserSession = ctx.obj["session"]
    page = session.get_page()
    step = Step(action="dismiss_modal", selector=selector)
    execute_action(page, step)
    _output({"dismissed": True})


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

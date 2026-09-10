"""``llm-browser-check``: run the conformance suite and report the table."""

import sys

import click

from llm_browser_conformance.drivers import CONFORMANCE_DRIVERS, installed_drivers
from llm_browser_conformance.runner import as_json, failed, format_table, run
from llm_browser_conformance.scenario import DEFAULT_DELAY_MS


@click.command()
@click.option(
    "--driver",
    "drivers",
    multiple=True,
    type=click.Choice(CONFORMANCE_DRIVERS),
    help="Driver to check; repeatable. Default: every installed driver.",
)
@click.option(
    "--only",
    "only",
    multiple=True,
    metavar="SUBSTRING",
    help="Run just the scenarios whose name contains SUBSTRING; repeatable.",
)
@click.option("--json", "as_json_output", is_flag=True, help="Machine-readable report.")
@click.option(
    "--delay",
    "delay_ms",
    default=DEFAULT_DELAY_MS,
    show_default=True,
    metavar="MS",
    help="How long the fixture pages take to change. Raise it on a slow machine.",
)
def main(
    drivers: tuple[str, ...], only: tuple[str, ...], as_json_output: bool, delay_ms: int
) -> None:
    """Run every conformance scenario against one or all installed drivers.

    Exits non-zero if any scenario failed, or if a driver's known gap has
    closed — a stale gap table is a lie about what the drivers do.
    """
    selected = list(drivers) or installed_drivers()
    results = run(selected, only, delay_ms)
    report = (
        as_json(results, selected, delay_ms)
        if as_json_output
        else format_table(results, selected)
    )
    click.echo(report)
    sys.exit(1 if failed(results) else 0)

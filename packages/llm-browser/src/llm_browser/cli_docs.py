"""``llm-browser docs``: keep the generated reference in step with the models.

Registered on the same group as the rest; it lives here because it is the one
command that touches the source tree rather than a browser.
"""

import click

from llm_browser.docgen import stale_reference, write_reference


@click.command()
@click.option("--write", is_flag=True, help="Rewrite the files from the models.")
@click.option("--check", is_flag=True, help="Report drift and exit 1. The default.")
def docs(write: bool, check: bool) -> None:
    """Regenerate or verify the reference docs the wheel ships.

    Options:
      --write  rewrite docs/reference/*.md from the models
      --check  fail when a shipped file no longer matches them
    """
    if write and check:
        raise click.UsageError("--write and --check are opposites; pass one.")
    if write:
        changed = write_reference()
        click.echo("\n".join(changed) if changed else "up to date")
        return
    stale = stale_reference()
    if stale:
        raise click.ClickException(
            f"stale: {', '.join(stale)} — regenerate with `llm-browser docs --write`"
        )
    click.echo("up to date")

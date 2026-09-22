"""``llm-browser docs``: keep the generated reference in step with the source.

A maintainer command on a user-facing CLI: the reference is a build artifact,
so both flags need the source tree the wheel was built from.
"""

from pathlib import Path

import click

import llm_browser


def source_tree() -> Path | None:
    """The ``src`` directory this package was imported from, or ``None`` when
    it is an installed wheel with no source beside it."""
    source = Path(llm_browser.__file__).resolve().parents[1]
    checkout = source.name == "src" and (source.parent / "pyproject.toml").exists()
    return source if checkout else None


@click.command()
@click.option("--write", is_flag=True, help="Rewrite the files from the source.")
@click.option("--check", is_flag=True, help="Report drift and exit 1. The default.")
def docs(write: bool, check: bool) -> None:
    """Regenerate or verify the reference docs the wheel ships."""
    if write and check:
        raise click.UsageError("--write and --check are opposites; pass one.")
    source = source_tree()
    if source is None:
        raise click.ClickException(
            "no source tree beside the installed package; this command only "
            "runs from a checkout of llm-browser"
        )
    from llm_browser.docgen import stale_reference, write_reference

    if write:
        changed = write_reference(source)
        click.echo("\n".join(changed) if changed else "up to date")
        return
    stale = stale_reference(source)
    if stale:
        raise click.ClickException(
            f"stale: {', '.join(stale)} — regenerate with `llm-browser docs --write`"
        )
    click.echo("up to date")

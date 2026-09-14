"""How every CLI command answers: one JSON line on stdout."""

import json

import click


def output(data: object) -> None:
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

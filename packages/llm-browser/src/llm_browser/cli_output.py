import json

import click


def output(data: object) -> None:
    """A ``FlowError`` is an expected runtime failure: it exits non-zero so callers detect it without parsing JSON."""
    from pydantic import BaseModel

    from llm_browser.models import FlowError

    if isinstance(data, BaseModel):
        click.echo(data.model_dump_json(exclude_none=True))
    else:
        click.echo(json.dumps(data, ensure_ascii=False))
    if isinstance(data, FlowError):
        raise SystemExit(1)

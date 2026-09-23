# ocampor-bench

The small pieces several repos would otherwise copy, one module per capability.
A bare install pulls no third-party dependency; each capability that needs one is an extra.

| Module | Extra | What |
| --- | --- | --- |
| `bench.docs.render`, `.files`, `.hook` | `docs` | griffe2md reference docs rendered at build time, with drift detection |
| `bench.docs.sections` | none | `sections_of(text)`: fence-aware split at `#`–`###` headings |

Without the extra, `bench.docs.render` (and anything importing it) raises an `ImportError` naming `ocampor-bench[docs]`.

## Install

```bash
pip install 'ocampor-bench[docs]' --index-url https://pypi.ocampor.com/simple/
```

## Quickstart

The blocks below are `example/`, kept in sync by `uv run python scripts/readme.py`.

`src/<package>/docgen.py` names what to document; the hook finds it by the name `REFERENCE`.

```python title="src/sample/docgen.py"
from bench.docs.files import Reference
from bench.docs.render import Document

REFERENCE = Reference(
    package="sample",
    header="<!-- generated -->\n",
    documents={
        "reference/models": Document("Models", "The sample's models.", ("models.Answer",), (("About", "models"),))
    },
)
```

`hatch_build.py`:

```python title="hatch_build.py"
from bench.docs.hook import ReferenceDocsHook  # noqa: F401
```

`pyproject.toml`:

```toml title="pyproject.toml"
[project]
name = "sample"
version = "0"

[build-system]
requires = ["hatchling", "ocampor-bench[docs]>=0.1,<0.2"]

[tool.hatch.build.hooks.custom]
path = "hatch_build.py"
package = "sample"

[tool.hatch.build.targets.wheel]
packages = ["src/sample"]
artifacts = ["/src/sample/docs/reference/*.md"]
```

A staleness test calls `stale_reference(REFERENCE, source)` from `bench.docs.files` and expects `[]`.

## Graduation rule

A module that grows past ~300 lines, gains a second dependency, or would be useful outside these repos
becomes its own package, as `cf-access` did. The bench is for what is too small to release alone.

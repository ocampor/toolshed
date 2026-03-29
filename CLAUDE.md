# Toolshed

Shared Python packages monorepo · Python 3.13+ · uv · hatchling · ruff · mypy · pytest

## Packages

- `packages/yaml-engine` — Generic YAML-driven engine: registry, conditions, compilation, template substitution
- `packages/fxrates` — Exchange rate client (Frankfurter/ECB API)
- `packages/llm-browser` — Playwright browser automation with declarative YAML flows

## Commands

Each package is independent. Always `cd` into the package before running commands.

- Install: `cd packages/<pkg> && uv sync`
- Test: `uv run pytest tests/path/to/test_file.py::test_function_name -v`
- Lint: `uv run ruff check --fix && uv run ruff format --check`
- Type check: `uv run mypy .`
- Only test affected functions. Run linter and type check as validation.

## Code Style

- Formatting enforced by `ruff format` (Black-compatible)
- Imports sorted by `ruff` (stdlib > third-party > local)
- Native type hints (`list[str]`, not `List[str]`)
- snake_case for functions/variables, PascalCase for classes
- Functions < 30 lines, single-purpose
- Files < 300 lines; refactor when exceeding
- `pathlib.Path` over `os.path`
- Pydantic models over raw dicts for structured data (return types, state, params)
- Constants centralized in `constants.py`, always public
- External `.js` files in `js/` directory, loaded via `scripts.py` with `lru_cache`
- No utility code in `__init__.py` — create dedicated modules
- Prefer libraries over hand-rolled parsers

## Testing

- Functional tests with `pytest` — no classes
- `@pytest.parametrize` for cases that vary only by input/expected output
- `@pytest.fixture` for shared setup; helper factories for repetitive constructors within a file
- Eliminate duplication: if the same object appears in multiple tests, extract a fixture or helper
- Write tests for every new piece of functionality

## Design

- Favor simplicity; only implement what's requested
- Follow existing code patterns when fixing bugs
- Single responsibility: each function does exactly one thing
- Don't over-engineer: avoid abstractions when a simple approach suffices
- When adding deps: update `pyproject.toml` → `uv lock` → `uv sync`

## Package Conventions

- Build backend: `hatchling` with `src/` layout
- Each package has its own `pyproject.toml`, `uv.lock`, and dev dependencies
- Cross-package deps use `[tool.uv.sources]` with relative paths
- `yaml_engine.registry.Registry[T]` for all extensible dispatch (conditions, actions, fields, params)
- `@lru_cache(maxsize=1)` singleton pattern for registry getters
- If a function is tested or importable, make it public — no underscore prefix on reusable code

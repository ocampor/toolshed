#!/usr/bin/env bash
#
# Lint, type-check, and test a single toolshed package, exactly as CLAUDE.md
# prescribes. Runnable locally and from CI.
#
# Usage: validate.sh <package-dir>     e.g. validate.sh packages/cf-access
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
package_dir="${1:?usage: validate.sh <package-dir>}"

cd "$repo_root/$package_dir"

uv sync                       # install the package and its dev tools
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
uv run mypy .                 # types
uv run pytest -q              # tests

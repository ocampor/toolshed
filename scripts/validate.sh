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

uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest -q

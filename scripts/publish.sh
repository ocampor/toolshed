#!/usr/bin/env bash
# Build a toolshed package and upload it to the private index (pypi.ocampor.com).
#
# Usage: scripts/publish.sh <package-dir>     e.g. scripts/publish.sh packages/cf-access
#
# Auth via env (the same vars consumers use to install):
#   UV_INDEX_OCAMPOR_USERNAME / UV_INDEX_OCAMPOR_PASSWORD
#
# pypiserver refuses to overwrite an existing version — bump `version` in the
# package's pyproject.toml before re-publishing.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
pkg="${1:?usage: publish.sh <package-dir>}"
cd "$root/$pkg"

: "${UV_INDEX_OCAMPOR_USERNAME:?set UV_INDEX_OCAMPOR_USERNAME}"
: "${UV_INDEX_OCAMPOR_PASSWORD:?set UV_INDEX_OCAMPOR_PASSWORD}"

rm -rf dist
uv build
uv publish \
  --publish-url https://pypi.ocampor.com/ \
  --username "$UV_INDEX_OCAMPOR_USERNAME" \
  --password "$UV_INDEX_OCAMPOR_PASSWORD" \
  dist/*

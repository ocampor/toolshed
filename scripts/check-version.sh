#!/usr/bin/env bash
#
# Strict version gate: has this package's current version already been published
# to the private index? Exit 0 when the version is new (safe to publish), exit 3
# when it already exists (the caller fails the build, or skips on a re-seed).
#
# Needs UV_INDEX_OCAMPOR_USERNAME / UV_INDEX_OCAMPOR_PASSWORD in the environment.
# Usage: check-version.sh <package-dir>     e.g. check-version.sh packages/cf-access
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
package_dir="${1:?usage: check-version.sh <package-dir>}"
: "${UV_INDEX_OCAMPOR_USERNAME:?set UV_INDEX_OCAMPOR_USERNAME}"
: "${UV_INDEX_OCAMPOR_PASSWORD:?set UV_INDEX_OCAMPOR_PASSWORD}"

index_url="${PYPI_INDEX_URL:-https://pypi.ocampor.com/simple}"

cd "$repo_root/$package_dir"

# Read a [project] field out of pyproject.toml (name, version, ...).
project_field() {
  python3 -c "import tomllib,sys; print(tomllib.load(open('pyproject.toml','rb'))['project'][sys.argv[1]])" "$1"
}

# The index lists distribution filenames like "cf_access-0.1.0-py3-none-any.whl"
# and "cf_access-0.1.0.tar.gz" — both carry "-<version>" followed by "." or "-".
version_on_index() {
  local listing
  listing="$(curl -fsS -u "$UV_INDEX_OCAMPOR_USERNAME:$UV_INDEX_OCAMPOR_PASSWORD" "$index_url/$name/" || true)"
  grep -qiE -- "-${version//./\\.}([.-])" <<<"$listing"
}

name="$(project_field name)"
version="$(project_field version)"

if version_on_index; then
  echo "$name $version is already on the index."
  exit 3
fi

echo "$name $version is new."

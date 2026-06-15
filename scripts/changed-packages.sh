#!/usr/bin/env bash
#
# Print the toolshed packages (one name per line) that changed between two git
# refs. With no refs it lists every package. Used by the CI workflow, and handy
# locally to preview what a push would publish.
#
# Usage:
#   changed-packages.sh                 # all packages
#   changed-packages.sh <base>          # changed since <base>
#   changed-packages.sh <base> <head>   # changed between <base> and <head>
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

# The changed file paths for the requested range — or every tracked file under
# packages/ when no range is given.
changed_files() {
  case $# in
    0) git ls-files -- 'packages/*' ;;
    1) git diff --name-only "$1" ;;
    *) git diff --name-only "$1" "$2" ;;
  esac
}

# "packages/cf-access/src/foo.py" -> "cf-access"
to_package_name() {
  sed -n 's,^packages/\([^/]*\)/.*,\1,p'
}

changed_files "$@" | to_package_name | sort -u

#!/usr/bin/env bash
# Run the test suite in a uv-managed virtualenv at ./venv (gitignored).
# The venv is created on first use and its test dependencies are synced on every run.
# Extra arguments are passed to pytest, eg. `./run-tests.sh test_tap_or_hold_specific.py -k rapid`.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv="$repo_root/venv"

if [ ! -x "$venv/bin/python" ]; then
    uv venv "$venv"
fi
uv pip install --quiet --python "$venv/bin/python" -e "$repo_root" -r "$repo_root/tests/requirements-test.txt"

cd "$repo_root/tests"
exec "$venv/bin/python" -m pytest "$@"

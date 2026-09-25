#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python -m pytest -q
python -m compileall -q outreach
for script in deploy/*.sh tools/*.sh; do bash -n "$script"; done

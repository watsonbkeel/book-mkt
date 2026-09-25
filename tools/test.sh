#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python -m pytest -q
python -m compileall -q outreach
bash -n deploy/setup.sh deploy/backup.sh deploy/upgrade.sh

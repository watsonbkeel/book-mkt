#!/usr/bin/env bash
set -euo pipefail
[[ $# -eq 2 ]] || { echo 'Usage: bash deploy/rollback.sh pre-upgrade.zip /new/empty/private-directory' >&2; exit 2; }
python3 "$(dirname "${BASH_SOURCE[0]}")/rollback.py" "$1" "$2"

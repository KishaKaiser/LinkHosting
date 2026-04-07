#!/usr/bin/env bash
# create-db.sh — Create a database for a site (delegates to lh.py)
# Usage: ./scripts/create-db.sh <site_name> [postgres|mysql]
set -euo pipefail
exec python3 "$(dirname "$0")/lh.py" create-db "$@"

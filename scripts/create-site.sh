#!/usr/bin/env bash
# create-site.sh — Create a new hosted site (delegates to lh.py)
# Usage: ./scripts/create-site.sh <name> <type> [--domain D] [--image I] [--upstream U] [--github URL] [--branch B]
set -euo pipefail
exec python3 "$(dirname "$0")/lh.py" create-site "$@"

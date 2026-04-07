#!/usr/bin/env bash
# create-cert.sh — Issue a TLS certificate for a site (delegates to lh.py)
# Usage: ./scripts/create-cert.sh <site_name>
set -euo pipefail
exec python3 "$(dirname "$0")/lh.py" cert "$@"

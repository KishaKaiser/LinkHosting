#!/usr/bin/env bash
# deploy-site.sh — Deploy a site (delegates to lh.py)
# Usage: ./scripts/deploy-site.sh <site_name>
set -euo pipefail
exec python3 "$(dirname "$0")/lh.py" deploy "$@"

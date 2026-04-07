#!/usr/bin/env bash
# create-sftp.sh — Create an SFTP account for a site (delegates to lh.py)
# Usage: ./scripts/create-sftp.sh <site_name>
set -euo pipefail
exec python3 "$(dirname "$0")/lh.py" create-sftp "$@"

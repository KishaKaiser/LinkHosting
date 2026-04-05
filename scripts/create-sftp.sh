#!/usr/bin/env bash
# create-sftp.sh — Create an SFTP account for a site
# Usage: ./scripts/create-sftp.sh <site_name>
#
# The plain-text password is returned ONCE. Store it securely.

set -euo pipefail

API_URL="${LINKHOSTING_API:-http://127.0.0.1:8000}"

[ $# -lt 1 ] && { echo "Usage: $0 <site_name>"; exit 1; }

SITE_NAME="$1"

echo "Creating SFTP account for site '$SITE_NAME'..."
RESULT=$(curl -sf -X POST "$API_URL/sites/$SITE_NAME/sftp")

echo "$RESULT" | python3 -m json.tool

SSH_HOST=$(echo "$RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['ssh_host'])")
SSH_PORT=$(echo "$RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['ssh_port'])")
USERNAME=$(echo "$RESULT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['username'])")

echo ""
echo "⚠  Store the password above — it will NOT be shown again."
echo ""
echo "SFTP connection:"
echo "  sftp -P $SSH_PORT $USERNAME@$SSH_HOST"

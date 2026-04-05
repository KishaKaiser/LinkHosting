#!/usr/bin/env bash
# create-db.sh — Create a database for a site
# Usage: ./scripts/create-db.sh <site_name> [postgres|mysql]
#
# The plain-text password is returned ONCE. Store it securely.

set -euo pipefail

API_URL="${LINKHOSTING_API:-http://127.0.0.1:8000}"

[ $# -lt 1 ] && { echo "Usage: $0 <site_name> [postgres|mysql]"; exit 1; }

SITE_NAME="$1"
ENGINE="${2:-postgres}"

PAYLOAD="{\"engine\": \"$ENGINE\"}"

echo "Creating $ENGINE database for site '$SITE_NAME'..."
RESULT=$(curl -sf -X POST "$API_URL/sites/$SITE_NAME/database" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")

echo "$RESULT" | python3 -m json.tool

echo ""
echo "⚠  Store the password above — it will NOT be shown again."

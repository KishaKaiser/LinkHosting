#!/usr/bin/env bash
# deploy-site.sh — Deploy (provision container + write vhost + reload proxy) for a site
# Usage: ./scripts/deploy-site.sh <site_name>

set -euo pipefail

API_URL="${LINKHOSTING_API:-http://127.0.0.1:8000}"

[ $# -lt 1 ] && { echo "Usage: $0 <site_name>"; exit 1; }

SITE_NAME="$1"

echo "Deploying site '$SITE_NAME'..."
curl -sf -X POST "$API_URL/sites/$SITE_NAME/deploy" | python3 -m json.tool

echo ""
echo "Site '$SITE_NAME' deployed."
echo "  DNS: Add an A record for the site's domain pointing to this host's IP."

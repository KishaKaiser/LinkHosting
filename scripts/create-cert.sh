#!/usr/bin/env bash
# create-cert.sh — Issue an internal TLS certificate for a site
# Usage: ./scripts/create-cert.sh <site_name>
#
# The cert is signed by the LinkHosting internal CA.
# To trust it on client machines, download the CA cert:
#   curl http://<host>:8000/ca.crt -o linkhosting-ca.crt
# Then follow docs/ca-trust.md for installation instructions.

set -euo pipefail

API_URL="${LINKHOSTING_API:-http://127.0.0.1:8000}"

[ $# -lt 1 ] && { echo "Usage: $0 <site_name>"; exit 1; }

SITE_NAME="$1"

echo "Issuing TLS certificate for site '$SITE_NAME'..."
curl -sf -X POST "$API_URL/sites/$SITE_NAME/cert" | python3 -m json.tool

echo ""
echo "Certificate issued. The proxy will now serve HTTPS for this site."
echo ""
echo "To trust the CA on client machines:"
echo "  curl http://\${LINKHOSTING_HOST:-127.0.0.1}:8000/ca.crt -o linkhosting-ca.crt"
echo "  See docs/ca-trust.md for full instructions."

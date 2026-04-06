#!/usr/bin/env bash
# create-site.sh — Create a new hosted site via the LinkHosting control-plane API
# Usage: ./scripts/create-site.sh <name> <type> [--domain <domain>] [--image <image>] [--upstream <url>]
#
# Types: static | php | node | python | proxy
# Example:
#   ./scripts/create-site.sh myapp node
#   ./scripts/create-site.sh myproxy proxy --upstream http://192.168.4.50:3000

set -euo pipefail

API_URL="${LINKHOSTING_API:-http://127.0.0.1:8000}"

usage() {
    echo "Usage: $0 <name> <type> [--domain <domain>] [--image <image>] [--upstream <url>]"
    echo "  type: static | php | node | python | proxy"
    exit 1
}

[ $# -lt 2 ] && usage

SITE_NAME="$1"
SITE_TYPE="$2"
shift 2

DOMAIN=""
IMAGE=""
UPSTREAM=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)   DOMAIN="$2";   shift 2 ;;
        --image)    IMAGE="$2";    shift 2 ;;
        --upstream) UPSTREAM="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

PAYLOAD=$(python3 -c "
import json, sys

d = {'name': sys.argv[1], 'site_type': sys.argv[2]}
if sys.argv[3]: d['domain'] = sys.argv[3]
if sys.argv[4]: d['image'] = sys.argv[4]
if sys.argv[5]: d['upstream_url'] = sys.argv[5]
print(json.dumps(d))
" "$SITE_NAME" "$SITE_TYPE" "$DOMAIN" "$IMAGE" "$UPSTREAM")

echo "Creating site '$SITE_NAME' (type=$SITE_TYPE)..."
curl -sf -X POST "$API_URL/sites" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" | python3 -m json.tool

echo ""
echo "Site '$SITE_NAME' created. Next steps:"
echo "  Deploy:    ./scripts/deploy-site.sh $SITE_NAME"
echo "  TLS cert:  ./scripts/create-cert.sh $SITE_NAME"
echo "  Database:  ./scripts/create-db.sh $SITE_NAME"
echo "  SFTP:      ./scripts/create-sftp.sh $SITE_NAME"

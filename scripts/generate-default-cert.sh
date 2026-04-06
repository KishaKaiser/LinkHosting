#!/usr/bin/env bash
# generate-default-cert.sh — Generate a self-signed cert for Nginx default server block
# Run this once during initial setup before starting the proxy
set -euo pipefail

CERT_DIR="/data/certs/default"
mkdir -p "$CERT_DIR"

openssl req -x509 -nodes -days 3650 \
  -newkey rsa:2048 \
  -keyout "$CERT_DIR/key.pem" \
  -out "$CERT_DIR/cert.pem" \
  -subj "/CN=linkhosting-default"

echo "Default cert generated in $CERT_DIR"

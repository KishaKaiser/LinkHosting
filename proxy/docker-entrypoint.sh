#!/bin/sh
# docker-entrypoint.sh — ensure default self-signed cert exists before nginx starts
set -e

CERT_DIR="/etc/nginx/certs/default"

if [ ! -f "$CERT_DIR/cert.pem" ]; then
    mkdir -p "$CERT_DIR"
    openssl req -x509 -nodes -days 3650 \
        -newkey rsa:2048 \
        -keyout "$CERT_DIR/key.pem" \
        -out "$CERT_DIR/cert.pem" \
        -subj "/CN=linkhosting-default" \
        2>/dev/null
    echo "Generated default TLS cert for Nginx default_server"
fi

exec "$@"

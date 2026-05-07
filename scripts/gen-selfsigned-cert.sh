#!/bin/bash
# Generate a self-signed TLS certificate for development/local use.
# For production, replace cert.pem + key.pem with real certificates from
# Let's Encrypt (certbot), your CA, or a wildcard cert.
set -e

DOMAIN="${1:-monitoring.local}"
SSL_DIR="configs/nginx/ssl"

mkdir -p "${SSL_DIR}"

openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout "${SSL_DIR}/key.pem" \
  -out    "${SSL_DIR}/cert.pem" \
  -subj "/C=US/ST=Dev/L=Local/O=MonitoringStack/CN=*.${DOMAIN}" \
  -addext "subjectAltName=DNS:*.${DOMAIN},DNS:${DOMAIN},DNS:localhost,IP:127.0.0.1"

echo "✔  Self-signed certificate written to ${SSL_DIR}/"
echo "   Valid for: *.${DOMAIN}, ${DOMAIN}, localhost"
echo "   Expires:   $(openssl x509 -noout -enddate -in ${SSL_DIR}/cert.pem | cut -d= -f2)"
echo ""
echo "   For Chrome/Firefox trust, import cert.pem into your browser's CA store."

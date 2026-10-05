#!/usr/bin/env bash
# Renew Let's Encrypt certificates (only when due), copy them where nginx reads them, and reload nginx.  Usage: scripts/renew-certs.sh <hostname>
set -euo pipefail
cd "$(dirname "$0")/.."
host="${1:?usage: renew-certs.sh <hostname>}"
docker compose --profile certbot run --rm certbot renew --webroot -w /var/www/certbot --quiet
live="deploy/certs-le/live/$host"
[ -f "$live/fullchain.pem" ] || { echo "no certificate for $host under $live - run the first 'certonly' command from docs/DEPLOYMENT.md" >&2; exit 1; }
if ! cmp -s "$live/fullchain.pem" deploy/certs/fullchain.pem 2>/dev/null; then
  mkdir -p deploy/certs
  cp -L "$live/fullchain.pem" deploy/certs/fullchain.pem && cp -L "$live/privkey.pem" deploy/certs/privkey.pem && chmod 600 deploy/certs/privkey.pem
  docker compose exec -T edge nginx -s reload || docker compose restart edge
  echo "certificate updated and nginx reloaded"
else
  echo "certificate unchanged"
fi

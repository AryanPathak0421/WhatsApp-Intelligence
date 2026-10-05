#!/usr/bin/env bash
# Generate a production .env from .env.example with fresh random secrets. Never overwrites an existing .env.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -e .env ] && { echo ".env already exists - refusing to overwrite. Move it away first." >&2; exit 1; }
hex() { openssl rand -hex "$1"; }
cat > .env <<EOF
# Generated $(date -u +%FT%TZ) by scripts/gen-secrets.sh - keep this file private (chmod 600), back it up separately from the data.
PUBLIC_URL=https://CHANGE_ME.example.com
POSTGRES_PASSWORD=$(hex 24)
REDIS_PASSWORD=$(hex 24)
JWT_ACCESS_SECRET=$(hex 32)
JWT_REFRESH_SECRET=$(hex 32)
# Encrypts uploaded chats and phone numbers at rest. LOSING THIS KEY MAKES THAT DATA UNREADABLE - store a copy in your password manager.
FIELD_ENCRYPTION_KEY=$(hex 32)
AI_ENGINE_TOKEN=$(hex 24)
UPLOAD_TTL_HOURS=24
EMBED_MODEL=intfloat/multilingual-e5-small
EOF
chmod 600 .env
echo "Wrote .env. Edit PUBLIC_URL, then:  docker compose --profile setup run --rm model-fetch  &&  docker compose up -d --build"

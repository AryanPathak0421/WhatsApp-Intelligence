#!/usr/bin/env bash
# Validate docker-compose.yml with dummy values (no secrets needed, no daemon needed).
set -euo pipefail
cd "$(dirname "$0")/.."
PUBLIC_URL=https://example.test POSTGRES_PASSWORD=x REDIS_PASSWORD=x JWT_ACCESS_SECRET=x JWT_REFRESH_SECRET=x FIELD_ENCRYPTION_KEY=x AI_ENGINE_TOKEN=x \
  docker compose --profile backup --profile setup config -q && echo "docker-compose.yml: valid"
for f in scripts/*.sh; do bash -n "$f" && echo "$f: syntax ok"; done

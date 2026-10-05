#!/usr/bin/env bash
# Restore a backup made by backup.sh.   scripts/restore.sh <db-dump-file> [uploads-tarball]
# Verifies the manifest checksum first, restores into the EXISTING empty database (--clean --if-exists drops our objects first).
# Env: PGHOST PGUSER PGPASSWORD PGDATABASE, UPLOAD_DIR (default /data/uploads), PG_RESTORE override for testing.
# STOP the backend and worker before restoring:  docker compose stop backend worker
set -euo pipefail
dump="${1:?usage: restore.sh <db-dump-file> [uploads-tarball]}"
tarball="${2:-}"
PG_RESTORE="${PG_RESTORE:-pg_restore}"
UPLOAD_DIR="${UPLOAD_DIR:-/data/uploads}"

manifest="$(dirname "$dump")/manifest-$(basename "$dump" | sed -E 's/^db-(.*)\.dump$/\1/').sha256"
if [ -f "$manifest" ]; then
  ( cd "$(dirname "$dump")" && sha256sum -c "$(basename "$manifest")" ) || { echo "checksum mismatch - backup is corrupt, aborting" >&2; exit 1; }
else
  echo "warning: no manifest next to the dump, skipping checksum verification" >&2
fi

"$PG_RESTORE" --clean --if-exists --no-owner --no-privileges --exit-on-error --dbname="${PGDATABASE:?set PGDATABASE}" "$dump"

if [ -n "$tarball" ]; then
  mkdir -p "$UPLOAD_DIR"
  tar -C "$UPLOAD_DIR" -xzf "$tarball"
fi
echo "restore complete. Start the stack again and check /health; the FIELD_ENCRYPTION_KEY must be the one used when the backup was taken."

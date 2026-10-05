#!/usr/bin/env bash
# Backup = custom-format pg_dump of the database + tarball of the (already encrypted) uploads volume.
# Env: PGHOST PGUSER PGPASSWORD PGDATABASE (standard libpq), BACKUP_DIR (default /backups), UPLOAD_DIR (default /data/uploads),
#      BACKUP_KEEP_DAYS (default 14), PG_DUMP / TAR overrides for testing.
# The FIELD_ENCRYPTION_KEY (.env) is NOT in the backup on purpose: store it separately, or encrypted uploads/phones are unreadable after restore.
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-/backups}"
UPLOAD_DIR="${UPLOAD_DIR:-/data/uploads}"
KEEP="${BACKUP_KEEP_DAYS:-14}"
PG_DUMP="${PG_DUMP:-pg_dump}"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
umask 077

db="$BACKUP_DIR/db-$stamp.dump"
"$PG_DUMP" --format=custom --no-owner --no-privileges --file="$db.partial"
mv "$db.partial" "$db"

if [ -d "$UPLOAD_DIR" ] && [ -n "$(ls -A "$UPLOAD_DIR" 2>/dev/null)" ]; then
  tar -C "$UPLOAD_DIR" -czf "$BACKUP_DIR/uploads-$stamp.tar.gz.partial" .
  mv "$BACKUP_DIR/uploads-$stamp.tar.gz.partial" "$BACKUP_DIR/uploads-$stamp.tar.gz"
fi

( cd "$BACKUP_DIR" && sha256sum db-"$stamp".dump $(ls uploads-"$stamp".tar.gz 2>/dev/null) > "manifest-$stamp.sha256" )

# retention
find "$BACKUP_DIR" -maxdepth 1 -type f \( -name 'db-*.dump' -o -name 'uploads-*.tar.gz' -o -name 'manifest-*.sha256' \) -mtime "+$KEEP" -delete
echo "backup $stamp ok: $(basename "$db")"

#!/usr/bin/env bash
# Round-trip test for backup.sh / restore.sh against a SCRATCH PostgreSQL server (creates and drops two throw-away databases).
#   PGHOST=localhost PGPORT=5432 PGUSER=postgres PGPASSWORD=... scripts/test-backup-restore.sh
# Optional: PSQL, PG_DUMP, PG_RESTORE to point at specific client binaries. Needs a role allowed to CREATE DATABASE.
set -euo pipefail
export PGCLIENTENCODING=UTF8   # the test text is UTF-8 (Windows psql defaults to the console code page)
here="$(cd "$(dirname "$0")" && pwd)"
PSQL="${PSQL:-psql}"; export PG_DUMP="${PG_DUMP:-pg_dump}"; export PG_RESTORE="${PG_RESTORE:-pg_restore}"
SRC="wa_bk_src_$$"; DST="wa_bk_dst_$$"; work="$(mktemp -d)"
cleanup() { for d in "$SRC" "$DST"; do PGDATABASE=postgres "$PSQL" -qc "DROP DATABASE IF EXISTS $d" >/dev/null 2>&1 || true; done; rm -rf "$work"; }
trap cleanup EXIT
# SQL goes through stdin: on Windows a non-ASCII command-line argument is mangled by the console code page before psql sees it
q() { printf '%s' "$2" | PGDATABASE="$1" "$PSQL" -qtA; }
fail() { echo "FAIL: $*" >&2; exit 1; }

PGDATABASE=postgres "$PSQL" -qc "CREATE DATABASE $SRC ENCODING 'UTF8' TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C'"
q "$SRC" "CREATE TABLE \"ChatMessage\" (id text primary key, body text not null, ts timestamptz default now());
          INSERT INTO \"ChatMessage\" VALUES ('m1','Razorpay integration ho gaya ✅'),('m2','फ्रंटएंड complete ho gaya 👍'),('m3','plain ascii');"
mkdir -p "$work/uploads" "$work/backups"; head -c 4096 /dev/urandom > "$work/uploads/aaaa-1111"; head -c 2048 /dev/urandom > "$work/uploads/bbbb-2222"

# --- 1. backup
PGDATABASE="$SRC" BACKUP_DIR="$work/backups" UPLOAD_DIR="$work/uploads" bash "$here/backup.sh" >/dev/null
dump="$(ls "$work"/backups/db-*.dump)"; tarball="$(ls "$work"/backups/uploads-*.tar.gz)"
[ -s "$dump" ] && [ -s "$tarball" ] && ls "$work"/backups/manifest-*.sha256 >/dev/null || fail "backup artefacts missing"
echo "ok  backup produced dump + uploads tarball + manifest"

# --- 2. restore into an empty database and compare
PGDATABASE=postgres "$PSQL" -qc "CREATE DATABASE $DST ENCODING 'UTF8' TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C'"
mkdir -p "$work/restored"
PGDATABASE="$DST" UPLOAD_DIR="$work/restored" bash "$here/restore.sh" "$dump" "$tarball" >/dev/null
[ "$(q "$DST" 'select count(*) from "ChatMessage"')" = "3" ] || fail "row count differs after restore"
[ "$(q "$DST" "select body from \"ChatMessage\" where id='m2'")" = "फ्रंटएंड complete ho gaya 👍" ] || fail "Unicode text changed in the round trip"
cmp "$work/uploads/aaaa-1111" "$work/restored/aaaa-1111" && cmp "$work/uploads/bbbb-2222" "$work/restored/bbbb-2222" || fail "upload files differ after restore"
echo "ok  restore reproduces rows (incl. Devanagari + emoji) and upload files byte-for-byte"

# --- 3. restoring over a populated database replaces it (idempotent)
q "$DST" "INSERT INTO \"ChatMessage\" VALUES ('junk','should disappear')"
PGDATABASE="$DST" UPLOAD_DIR="$work/restored" bash "$here/restore.sh" "$dump" >/dev/null
[ "$(q "$DST" 'select count(*) from "ChatMessage"')" = "3" ] || fail "second restore did not replace existing data"
echo "ok  re-restore over existing data replaces it"

# --- 4. a corrupted backup is refused before anything is touched
mkdir -p "$work/c"; cp "$dump" "$work/c/"; cp "$work"/backups/manifest-*.sha256 "$work/c/"
printf 'X' | dd of="$work/c/$(basename "$dump")" bs=1 seek=100 conv=notrunc 2>/dev/null
if PGDATABASE="$DST" bash "$here/restore.sh" "$work/c/$(basename "$dump")" >/dev/null 2>&1; then fail "corrupted dump was accepted"; fi
[ "$(q "$DST" 'select count(*) from "ChatMessage"')" = "3" ] || fail "database changed despite refused restore"
echo "ok  corrupted backup refused, database untouched"

# --- 5. retention deletes only old backups
touch -d "30 days ago" "$work/backups/db-20000101T000000Z.dump" "$work/backups/manifest-20000101T000000Z.sha256"
PGDATABASE="$SRC" BACKUP_DIR="$work/backups" UPLOAD_DIR="$work/uploads" BACKUP_KEEP_DAYS=14 bash "$here/backup.sh" >/dev/null
[ ! -e "$work/backups/db-20000101T000000Z.dump" ] && ls "$work"/backups/db-2*Z.dump >/dev/null || fail "retention did not prune old backups (or removed new ones)"
echo "ok  retention prunes old backups only"
echo "ALL BACKUP/RESTORE CHECKS PASSED"

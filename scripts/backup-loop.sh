#!/usr/bin/env bash
# Runs backup.sh every night at ~02:30 (container local time) inside the `backup` compose profile.
set -u
while true; do
  now=$(date +%s)
  next=$(date -d "02:30" +%s 2>/dev/null || echo $((now + 86400)))
  [ "$next" -le "$now" ] && next=$((next + 86400))
  sleep $((next - now))
  /bin/bash /scripts/backup.sh || echo "BACKUP FAILED at $(date -u +%FT%TZ)" >&2
done

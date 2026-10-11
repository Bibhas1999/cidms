#!/usr/bin/env bash
# Nightly database backup (cron, 02:30). A full copy in Postgres's own format, kept 30 days:
#   /opt/supreme-dms/backups/supreme-2026-10-12-0230.dump
# Restore with deploy/restore.sh. Copy the folder off the server now and then (or set RCLONE_REMOTE below).
set -euo pipefail
cd /opt/supreme-dms
KEEP_DAYS=30
RCLONE_REMOTE="${RCLONE_REMOTE:-}"   # e.g. "oci:supreme-backups" once rclone is set up (optional)
file="backups/supreme-$(date +%F-%H%M).dump"

sudo docker compose -f deploy/docker-compose.prod.yml --env-file .env.production exec -T postgres \
  pg_dump -U supreme_owner -d supreme --format=custom --compress=9 > "$file.part"
mv "$file.part" "$file"
# A backup that can't be read is no backup: list its contents as a check.
sudo docker compose -f deploy/docker-compose.prod.yml --env-file .env.production exec -T postgres pg_restore --list < "$file" > /dev/null
echo "$(date '+%F %T') backup ok: $file ($(du -h "$file" | cut -f1))"

find backups -name 'supreme-*.dump' -mtime +"$KEEP_DAYS" -delete
if [ -n "$RCLONE_REMOTE" ] && command -v rclone >/dev/null; then
  rclone copy "$file" "$RCLONE_REMOTE" && echo "copied off the server to $RCLONE_REMOTE"
fi

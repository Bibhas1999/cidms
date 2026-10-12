#!/usr/bin/env bash
# Database backups, on the schedule set in the app (Settings > Backups on the platform: time, how often, how
# long to keep). Cron runs this every 5 minutes with --if-due (deploy/backup.cron); it asks the app whether a
# backup is due (or "Back up now" was pressed), makes it, and reports back. By hand: deploy/backup.sh
#   A full copy in Postgres's own format: /opt/supreme-dms/backups/supreme-2026-10-12-2300.dump
# Restore with deploy/restore.sh. Copy the folder off the server now and then (or set RCLONE_REMOTE below).
set -euo pipefail
cd /opt/supreme-dms
RCLONE_REMOTE="${RCLONE_REMOTE:-}"   # e.g. "oci:supreme-backups" once rclone is set up (optional)
dc() { sudo docker compose -f deploy/docker-compose.prod.yml --env-file .env.production "$@"; }

if [ "${1:-}" = "--if-due" ]; then
  due=$(dc exec -T app python -m app.manage backup-start | tail -n 1)
else
  due=$(dc exec -T app python -m app.manage backup-start --now | tail -n 1)
fi
[ -n "$due" ] || exit 0   # nothing due
read -r run_id KEEP_DAYS <<< "$due"

file="backups/supreme-$(date +%F-%H%M).dump"
fail() {
  echo "$(date '+%F %T') backup FAILED: $1"
  rm -f "$file.part"
  dc exec -T app python -m app.manage backup-finish "$run_id" failed --message "$1" || true
  exit 1
}
dc exec -T postgres pg_dump -U supreme_owner -d supreme --format=custom --compress=9 > "$file.part" || fail "The database copy didn't finish."
mv "$file.part" "$file"
# A backup that can't be read is no backup: list its contents as a check.
dc exec -T postgres pg_restore --list < "$file" > /dev/null || fail "The copy was made but can't be read back."
size=$(stat -c %s "$file")
dc exec -T app python -m app.manage backup-finish "$run_id" ok --file "$file" --bytes "$size"
echo "$(date '+%F %T') backup ok: $file ($(du -h "$file" | cut -f1))"

find backups -name 'supreme-*.dump' -mtime +"$KEEP_DAYS" -delete
if [ -n "$RCLONE_REMOTE" ] && command -v rclone >/dev/null; then
  rclone copy "$file" "$RCLONE_REMOTE" && echo "copied off the server to $RCLONE_REMOTE"
fi

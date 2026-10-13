#!/usr/bin/env bash
# Put a backup back: replaces everything in the database with the backup's contents (every centre).
#   From the app: Settings > Backups > Restore. Cron runs this every minute with --if-requested (deploy/backup.cron).
#   By hand:      bash deploy/restore.sh backups/supreme-2026-10-12-2300.dump
# Either way:
#   1. the data as it is now is backed up first (supreme-<when>-before-restore.dump), so a restore can be undone;
#   2. the copy goes in as one transaction: if it fails, nothing has changed;
#   3. the tables are brought up to this version of the app (a copy may be from before an update);
#   4. the backup history stays as it was (it isn't put back to the copy's), and everyone signs in again.
# The app and worker are stopped while the copy goes in (a minute or two).
set -euo pipefail
cd /opt/supreme-dms
dc() { sudo docker compose -f deploy/docker-compose.prod.yml --env-file .env.production "$@"; }
manage() { dc exec -T app python -m app.manage "$@"; }

# One at a time with backups (deploy/backup.sh takes the same lock).
exec 9>backups/.lock
if [ "${1:-}" = "--if-requested" ]; then
  flock -n 9 || exit 0   # a backup is being made: next minute
  due=$(manage restore-start | tail -n 1)
  [ -n "$due" ] || exit 0
  read -r run_id dump <<< "$due"
else
  dump="${1:?which backup? e.g. backups/supreme-2026-10-12-2300.dump}"
  [ -f "$dump" ] || { echo "no such file: $dump"; exit 1; }
  read -r -p "This replaces ALL current data with $dump. Type RESTORE to go on: " answer
  [ "$answer" = "RESTORE" ] || { echo "stopped"; exit 1; }
  flock 9
  run_id=$(manage restore-start --file "$dump" | tail -n 1 | cut -d' ' -f1)
fi

history=$(mktemp)
work=$(mktemp)
restored=0
log() { echo "$(date '+%F %T') $*"; }
fail() {
  trap - ERR
  log "restore FAILED: $1"
  dc start app worker > /dev/null 2>&1 || true
  sleep 5
  if [ "$restored" = 1 ]; then manage history-load < "$history" || true; fi
  manage restore-finish "$run_id" failed --message "$1" || true
  rm -f "$history" "$work"
  exit 1
}
trap 'fail "Stopped at an unexpected step (see backups/restore.log on the server)."' ERR

log "restore of $dump started"
[ -f "$dump" ] || fail "The backup file isn't on the server any more. Nothing was changed."
cp "$dump" "$work"   # a scheduled clean-up can't remove it half-way through

# 1. the data as it is now
safety="backups/supreme-$(date +%F-%H%M%S)-before-restore.dump"
dc exec -T postgres pg_dump -U supreme_owner -d supreme --format=custom --compress=9 > "$safety.part" \
  || fail "Couldn't back up the current data first. Nothing was changed."
mv "$safety.part" "$safety"
dc exec -T postgres pg_restore --list < "$safety" > /dev/null || fail "The backup of the current data can't be read back. Nothing was changed."
dc exec -T postgres pg_restore -f - < "$safety" | gzip -9 > "${safety%.dump}.sql.gz" || rm -f "${safety%.dump}.sql.gz"
manage backup-record --file "$safety" --bytes "$(stat -c %s "$safety")" --message "The data just before restoring $(basename "$dump")"
manage history-save > "$history" || fail "Couldn't read the backup history. Nothing was changed."

# 2. the copy goes in
dc stop app worker
dc exec -T postgres pg_restore -U supreme_owner -d supreme --clean --if-exists --no-owner --role=supreme_owner \
  --single-transaction < "$work" || fail "The backup couldn't be put back, so the data is as it was."
restored=1

# 3. tables up to this version, 4. history back, everyone signs in again
dc run --rm migrate || fail "The backup is back, but bringing its tables up to date failed. Restore $(basename "$safety") to undo."
dc start app worker
sleep 5
manage history-load < "$history"
manage restore-finish "$run_id" ok --message "Restored from $(basename "$dump"). The data before it is in $(basename "$safety")."
trap - ERR
rm -f "$history" "$work"
log "restore of $dump done (the data before it: $safety)"

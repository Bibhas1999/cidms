#!/usr/bin/env bash
# Put a backup back (replaces everything in the database with the backup's contents):
#   bash deploy/restore.sh backups/supreme-2026-10-12-0230.dump
# The app and worker are stopped while it runs and started again after.
set -euo pipefail
cd /opt/supreme-dms
dump="${1:?which backup? e.g. backups/supreme-2026-10-12-0230.dump}"
[ -f "$dump" ] || { echo "no such file: $dump"; exit 1; }
compose="sudo docker compose -f deploy/docker-compose.prod.yml --env-file .env.production"

read -r -p "This replaces ALL current data with $dump. Type RESTORE to go on: " answer
[ "$answer" = "RESTORE" ] || { echo "stopped"; exit 1; }

$compose stop app worker
$compose exec -T postgres pg_restore -U supreme_owner -d supreme --clean --if-exists --no-owner --role=supreme_owner \
  --single-transaction < "$dump"
$compose start app worker
echo "restored from $dump"

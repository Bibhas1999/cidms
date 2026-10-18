#!/bin/sh
# Go back to an earlier version of the app (the last five deploys are kept as supreme-dms:<commit>).
#
#   sudo deploy/rollback.sh            # the version before the current one
#   sudo deploy/rollback.sh 1a2b3c4d5e6f   # a particular one (see releases.log, or: docker image ls supreme-dms)
#
# Run from /opt/supreme-dms. Only the app and the worker change: the database stays as it is. Migrations are never
# undone, and they only add tables and columns, so an older version works with the newer database. If a release
# notes otherwise, restore the backup taken before it instead.
set -eu
cd "$(dirname "$0")/.."

if [ "${1:-}" ]; then
  target="$1"
else
  [ -f releases.log ] || { echo "No releases.log here: run from /opt/supreme-dms, or name the version."; exit 1; }
  current=$(tail -n 1 releases.log | awk '{print $2}')
  target=$(awk '{print $2}' releases.log | grep -v -x "$current" | tail -n 1)
  [ "$target" ] || { echo "No earlier version recorded in releases.log."; exit 1; }
fi

docker image inspect "supreme-dms:$target" > /dev/null 2>&1 || {
  echo "supreme-dms:$target isn't on this server any more. Kept versions:"; docker image ls supreme-dms; exit 1; }

echo "Switching the app and the worker to supreme-dms:$target …"
APP_VERSION="$target" docker compose -f deploy/docker-compose.prod.yml --env-file .env.production \
  up -d --no-build --no-deps app worker
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $target rollback" >> releases.log
docker compose -f deploy/docker-compose.prod.yml --env-file .env.production ps app worker

#!/bin/sh
# Restore a ParkSight database backup (Docker Compose deployment).
#   ./scripts/restore.sh backups/parksight-20261110-120000.dump
# REPLACES all current ParkSight data (configuration, users and history).
set -eu
cd "$(dirname "$0")/.."
FILE="${1:?usage: scripts/restore.sh <backup.dump>}"
[ -f "$FILE" ] || { echo "No such file: $FILE"; exit 1; }
printf 'This replaces ALL current ParkSight data with %s. Type RESTORE to continue: ' "$FILE"
read -r answer
[ "$answer" = "RESTORE" ] || { echo "Cancelled."; exit 1; }
docker compose stop parksight
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < "$FILE"
docker compose start parksight
echo "Restore complete. Pending migrations (if the backup is older) run automatically at start-up."

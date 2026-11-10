#!/bin/sh
# Back up the ParkSight database (Docker Compose deployment).
#   ./scripts/backup.sh            -> backups/parksight-YYYYmmdd-HHMMSS.dump
# Also back up .env (it contains PARKSIGHT_SECRET_KEY, needed to decrypt
# stored camera passwords) to a safe place.
set -eu
cd "$(dirname "$0")/.."
mkdir -p backups
FILE="backups/parksight-$(date +%Y%m%d-%H%M%S).dump"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$FILE"
echo "Backup written to $FILE ($(wc -c < "$FILE") bytes)"

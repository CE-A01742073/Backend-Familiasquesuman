#!/usr/bin/env bash
# Respaldo diario de PostgreSQL (comprimido) con rotación. Pensado para cron en la VM:
#   0 3 * * * /home/azureuser/familias-backend/scripts/respaldo.sh >> /home/azureuser/respaldos/respaldo.log 2>&1
set -euo pipefail

DIR_PROYECTO="$(cd "$(dirname "$0")/.." && pwd)"
DIR_RESPALDOS="${DIR_RESPALDOS:-$HOME/respaldos}"
DIAS_A_CONSERVAR="${DIAS_A_CONSERVAR:-7}"

cd "$DIR_PROYECTO"
set -a; . ./.env; set +a

mkdir -p "$DIR_RESPALDOS"
chmod 700 "$DIR_RESPALDOS"
archivo="$DIR_RESPALDOS/familias-$(date +%F-%H%M).sql.gz"

docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$archivo"
chmod 600 "$archivo"
find "$DIR_RESPALDOS" -name 'familias-*.sql.gz' -mtime +"$DIAS_A_CONSERVAR" -delete

echo "$(date -Is) respaldo ok: $archivo ($(du -h "$archivo" | cut -f1))"

#!/bin/sh
set -e
echo "→ Aplicando migraciones"
alembic upgrade head
if [ "${SEED_ON_START:-false}" = "true" ]; then
  echo "→ Carga inicial de datos (SEED_ON_START=true)"
  python -m scripts.seed ${SEED_DEMO:+--demo}
fi
echo "→ Iniciando API"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*" --no-server-header --no-date-header --workers "${WORKERS:-1}"

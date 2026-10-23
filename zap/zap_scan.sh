#!/usr/bin/env bash
# Escaneo OWASP ZAP (API scan) contra la API desplegada. Genera el reporte HTML/JSON para la evidencia de la Parte 2.
#
#   ./zap/zap_scan.sh https://api.tudominio.com            # sin sesión: prueba rutas públicas + auth
#   ./zap/zap_scan.sh https://api.tudominio.com "$TOKEN"   # con JWT: prueba rutas autenticadas (recomendado)
#
# Antes de escanear: agrega la IP pública de esta máquina a RATE_LIMIT_EXEMPT_IPS en .env (y quítala al terminar).
# Después de escanear: `docker compose exec api python -m scripts.seed --demo` para restaurar las cuentas demo.
# Se excluyen del escaneo las operaciones que invalidan la sesión del escáner (DELETE /me, logout, logout-todo);
# esas se cubren con pytest. Solo escanea servidores propios. Requiere Docker.
set -euo pipefail
URL="${1:?Uso: zap_scan.sh <url-base> [access_token]}"
TOKEN="${2:-}"
AQUI="$(cd "$(dirname "$0")" && pwd)"
RAIZ="$(cd "$AQUI/.." && pwd)"
mkdir -p "$AQUI/reportes"

echo "→ Exportando OpenAPI apuntando a $URL"
if (cd "$RAIZ" && docker compose ps --status running api 2>/dev/null | grep -q api); then
  (cd "$RAIZ" && docker compose exec -T api python -m scripts.export_openapi "$URL" > "$AQUI/openapi.json")
else
  (cd "$RAIZ" && python3 -m scripts.export_openapi "$URL" > "$AQUI/openapi.json")
fi

python3 - "$AQUI/openapi.json" <<'EOF'
import json, sys
ruta = sys.argv[1]
spec = json.load(open(ruta))
excluir = {("/api/v1/me", "delete"), ("/api/v1/auth/logout", "post"), ("/api/v1/auth/logout-todo", "post")}
for path, metodo in excluir:
    spec.get("paths", {}).get(path, {}).pop(metodo, None)
spec["paths"] = {p: ops for p, ops in spec["paths"].items() if ops}
json.dump(spec, open(ruta, "w"), indent=2)
print(f"→ Rutas a escanear: {sum(len(o) for o in spec['paths'].values())} (excluidas: {len(excluir)})")
EOF

EXTRA=()
if [ -n "$TOKEN" ]; then
  EXTRA=(-z "-config replacer.full_list(0).description=auth \
             -config replacer.full_list(0).enabled=true \
             -config replacer.full_list(0).matchtype=REQ_HEADER \
             -config replacer.full_list(0).matchstr=Authorization \
             -config replacer.full_list(0).regex=false \
             -config replacer.full_list(0).replacement=Bearer\ $TOKEN")
fi

FECHA="$(date +%Y%m%d-%H%M)"
docker run --rm -t \
  -v "$AQUI:/zap/wrk:rw" \
  ghcr.io/zaproxy/zaproxy:stable zap-api-scan.py \
  -t /zap/wrk/openapi.json -f openapi \
  -c zap.conf \
  -r "reportes/zap-$FECHA.html" -J "reportes/zap-$FECHA.json" \
  -I "${EXTRA[@]}" || true

echo "→ Reporte: $AQUI/reportes/zap-$FECHA.html"
echo "   Objetivo: 0 alertas High y 0 Medium. Las Informational/Low se documentan con justificación."
"""Exporta el OpenAPI (para ZAP, Postman o Retrofit) sin necesidad de /docs en producción.
Uso: JWT_SECRET=x... python -m scripts.export_openapi > openapi.json"""
import json
import os
import sys

os.environ.setdefault("ENV", "test")
os.environ.setdefault("JWT_SECRET", "solo-para-exportar-el-esquema-0123456789abcdef")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")

from app.main import app  # noqa: E402

spec = app.openapi()
if len(sys.argv) > 1:
    spec["servers"] = [{"url": sys.argv[1]}]
json.dump(spec, sys.stdout, ensure_ascii=False, indent=2)

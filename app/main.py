import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import text

from app.core.config import get_settings
from app.core.errors import registrar_manejadores
from app.core.middleware import registrar_middlewares
from app.db.session import engine
from app.routers import archivos, auth, catalogo, donaciones, gestion, inscripciones, me, mensajes, social, testimonios

settings = get_settings()
logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("familias")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ENV != "test":
        try:
            from app.core import storage

            storage.asegurar_bucket()
        except Exception as e:  # el API sigue arrancando; las fotos fallarán con error claro
            log.warning("No se pudo verificar el bucket S3: %s", e.__class__.__name__)
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="API de Familias que Suman: voluntariado familiar en Monterrey y Hermosillo.",
    lifespan=lifespan,
    # A02: sin documentación interactiva en producción (el spec se exporta con scripts/export_openapi.py)
    docs_url=None if settings.es_prod else "/docs",
    redoc_url=None,
    openapi_url=None if settings.es_prod else "/openapi.json",
)

registrar_middlewares(app)
registrar_manejadores(app)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
    )

# Métricas HTTP automáticas (latencia, status, rutas) + métricas de negocio en app.core.metrics
Instrumentator(
    should_group_status_codes=False,
    excluded_handlers=["/metrics", "/health"],
).instrument(app)

_bearer = HTTPBearer(auto_error=False)


@app.get("/metrics", include_in_schema=False)
async def metrics(cred: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    """Prometheus manda `Authorization: Bearer <METRICS_TOKEN>`. Sin token configurado → 404."""
    if not settings.METRICS_TOKEN:
        raise HTTPException(404, "Not Found")
    if cred is None or cred.credentials != settings.METRICS_TOKEN:
        raise HTTPException(401, "No autorizado")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health", include_in_schema=False)
async def health():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception:
        return Response('{"status":"db_error"}', status_code=503, media_type="application/json")


for r in (auth, me, catalogo, inscripciones, donaciones, testimonios, archivos, social, mensajes, gestion):
    app.include_router(r.router, prefix=settings.API_PREFIX)


@app.get(settings.API_PREFIX, include_in_schema=False)
async def raiz(request: Request):
    return {"nombre": settings.APP_NAME, "version": app.version}

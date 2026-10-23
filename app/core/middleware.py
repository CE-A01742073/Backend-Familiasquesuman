"""Middlewares: request-id, cabeceras de seguridad (A02) y límite de tamaño de cuerpo (A10)."""
import uuid

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import get_settings

CABECERAS_SEGURIDAD = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cache-Control": "no-store",
    "Cross-Origin-Resource-Policy": "same-origin",
}


async def _contiene_nul(request: Request) -> bool:
    if "\x00" in request.url.path or "%00" in request.url.query.lower():
        return True
    tipo = request.headers.get("content-type", "")
    if tipo.startswith("application/json"):
        cuerpo = await request.body()
        return b"\x00" in cuerpo or b"\\u0000" in cuerpo
    return False


class SeguridadMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        s = get_settings()
        request.state.request_id = request.headers.get("x-request-id", str(uuid.uuid4()))[:64]

        # Límite de tamaño declarado
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > s.MAX_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={"error": {"codigo": "demasiado_grande", "mensaje": "El cuerpo de la solicitud es demasiado grande"}},
            )

        if await _contiene_nul(request):
            return JSONResponse(
                status_code=400,
                content={"error": {"codigo": "entrada_invalida", "mensaje": "La solicitud contiene caracteres no permitidos"}},
            )

        response = await call_next(request)
        for k, v in CABECERAS_SEGURIDAD.items():
            response.headers.setdefault(k, v)
        if s.es_prod:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        response.headers["X-Request-Id"] = request.state.request_id
        if request.url.path.startswith(("/docs", "/redoc")):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data: https://fastapi.tiangolo.com"
            )
        return response


def registrar_middlewares(app: FastAPI) -> None:
    app.add_middleware(SeguridadMiddleware)


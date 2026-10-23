"""Manejo de errores (A10): nunca se filtra stack trace ni detalle interno al cliente."""
import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("familias.errores")


class ErrorApp(Exception):
    """Error de negocio con mensaje seguro para la persona usuaria."""

    def __init__(self, status: int, mensaje: str, codigo: str = "error"):
        self.status = status
        self.mensaje = mensaje
        self.codigo = codigo


def _respuesta(status: int, mensaje: str, codigo: str, request: Request, extra: dict | None = None) -> JSONResponse:
    cuerpo = {"error": {"codigo": codigo, "mensaje": mensaje, "request_id": getattr(request.state, "request_id", None)}}
    if extra:
        cuerpo["error"].update(extra)
    return JSONResponse(status_code=status, content=cuerpo)


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(ErrorApp)
    async def _error_app(request: Request, exc: ErrorApp):
        return _respuesta(exc.status, exc.mensaje, exc.codigo, request)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
        headers = getattr(exc, "headers", None)
        resp = _respuesta(exc.status_code, str(exc.detail), "http_error", request)
        if headers:
            for k, v in headers.items():
                resp.headers[k] = v
        return resp

    @app.exception_handler(HTTPException)
    async def _http2(request: Request, exc: HTTPException):
        return await _http(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validacion(request: Request, exc: RequestValidationError):
        # Solo campo y tipo de error; sin eco del valor enviado (evita reflejar payloads).
        detalles = []
        for e in exc.errors():
            if e.get("type") == "json_invalid":
                detalles.append({"campo": "body", "error": "JSON inválido"})
                continue
            detalles.append(
                {"campo": ".".join(str(p) for p in e.get("loc", []) if p != "body") or "body", "error": e.get("msg", "inválido")}
            )
        return _respuesta(422, "Datos inválidos", "validacion", request, {"detalles": detalles[:20]})

    @app.exception_handler(IntegrityError)
    async def _integridad(request: Request, exc: IntegrityError):
        log.warning("IntegrityError en %s: %s", request.url.path, exc.orig.__class__.__name__)
        return _respuesta(409, "La operación entra en conflicto con datos existentes", "conflicto", request)

    @app.exception_handler(Exception)
    async def _generico(request: Request, exc: Exception):
        rid = getattr(request.state, "request_id", str(uuid.uuid4()))
        log.exception("Error no controlado request_id=%s path=%s", rid, request.url.path)
        return _respuesta(500, "Ocurrió un error inesperado", "interno", request)

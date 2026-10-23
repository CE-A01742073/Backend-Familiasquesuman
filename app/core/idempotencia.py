"""Idempotencia para el sync offline: `Idempotency-Key` en POST → la misma respuesta en reintentos,
sin duplicar inscripciones, donaciones o testimonios."""
import re
import uuid
from typing import Annotated

from fastapi import Header, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import ahora
from app.models.participacion import ClaveIdempotencia

_FORMATO = re.compile(r"^[A-Za-z0-9_\-]{8,64}$")


def clave_idempotencia(idempotency_key: Annotated[str | None, Header()] = None) -> str | None:
    if idempotency_key is None:
        return None
    if not _FORMATO.match(idempotency_key):
        raise HTTPException(422, "Idempotency-Key inválida (8–64 caracteres alfanuméricos)")
    return idempotency_key


async def respuesta_previa(db: AsyncSession, usuario_id: uuid.UUID, clave: str | None, ruta: str) -> ClaveIdempotencia | None:
    if clave is None:
        return None
    prev = await db.get(ClaveIdempotencia, (usuario_id, clave))
    if prev and prev.ruta != ruta:
        raise HTTPException(422, "Idempotency-Key ya usada en otra operación")
    return prev


async def guardar_respuesta(
    db: AsyncSession, usuario_id: uuid.UUID, clave: str | None, ruta: str, status: int, cuerpo: dict
) -> None:
    if clave is None:
        return
    db.add(ClaveIdempotencia(usuario_id=usuario_id, clave=clave, ruta=ruta, status=status, cuerpo=cuerpo, creado_en=ahora()))


def reproducir(prev: ClaveIdempotencia, response: Response) -> dict:
    response.status_code = prev.status
    response.headers["Idempotent-Replayed"] = "true"
    return prev.cuerpo


def ruta_de(request: Request) -> str:
    return f"{request.method} {request.url.path}"

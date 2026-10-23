"""Entrega de imágenes desde S3/MinIO a través de la API (un solo host público, autorización por tipo)."""
import re

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select

from app.core import storage
from app.core.deps import DB, UsuarioActual
from app.core.ratelimit import limite_general
from app.models.participacion import EstadoModeracion, Testimonio
from app.models.usuarios import Familia, Rol

router = APIRouter(prefix="/archivos", tags=["archivos"], dependencies=[Depends(limite_general)])

# Solo keys generadas por el servidor: sin '..' ni rutas arbitrarias.
_KEY = re.compile(r"^(centros|actividades|campanas|proyectos|testimonios|perfiles)/[0-9a-f]{32}\.jpg$")


@router.get("/{key:path}")
async def obtener(key: str, usuario: UsuarioActual, db: DB):
    if not _KEY.match(key):
        raise HTTPException(404, "Archivo no encontrado")

    if key.startswith("testimonios/"):
        t = await db.scalar(select(Testimonio).where(Testimonio.foto_key == key))
        if t is None:
            raise HTTPException(404, "Archivo no encontrado")
        if t.estado != EstadoModeracion.aprobado and usuario.rol != Rol.admin:
            fam = await db.scalar(select(Familia.id).where(Familia.usuario_id == usuario.id))
            if fam != t.familia_id:
                raise HTTPException(404, "Archivo no encontrado")  # ni siquiera confirmamos que existe

    datos = await storage.leer(key)
    if datos is None:
        raise HTTPException(404, "Archivo no encontrado")
    return Response(
        content=datos,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600", "Content-Disposition": "inline"},
    )

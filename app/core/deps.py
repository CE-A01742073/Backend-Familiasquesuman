"""Dependencias de autenticación y autorización. Deny by default (A01)."""
import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import decodificar_access_token
from app.db.session import get_db
from app.models.usuarios import Familia, Rol, Usuario

_bearer = HTTPBearer(auto_error=False)

DB = Annotated[AsyncSession, Depends(get_db)]


def _no_autorizado(msg: str = "No autenticado") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, msg, headers={"WWW-Authenticate": "Bearer"})


async def usuario_actual(
    request: Request,
    db: DB,
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Usuario:
    if cred is None or cred.scheme.lower() != "bearer":
        raise _no_autorizado()
    try:
        claims = decodificar_access_token(cred.credentials)
        uid = uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise _no_autorizado("Token inválido o expirado")

    # El rol SIEMPRE se re-lee de la BD: un token viejo no conserva privilegios revocados.
    usuario = await db.get(Usuario, uid)
    if usuario is None or not usuario.activo or usuario.eliminado_en is not None:
        raise _no_autorizado("Cuenta no disponible")
    request.state.usuario_id = usuario.id
    return usuario


UsuarioActual = Annotated[Usuario, Depends(usuario_actual)]


def requiere_rol(*roles: Rol):
    async def _dep(usuario: UsuarioActual) -> Usuario:
        if usuario.rol not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No tienes permiso para esta acción")
        return usuario

    return _dep


Admin = Annotated[Usuario, Depends(requiere_rol(Rol.admin))]
Asociacion = Annotated[Usuario, Depends(requiere_rol(Rol.asociacion, Rol.admin))]
SoloFamilia = Annotated[Usuario, Depends(requiere_rol(Rol.familia))]


async def familia_actual(usuario: UsuarioActual, db: DB) -> Familia:
    if usuario.rol != Rol.familia:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Esta acción es solo para familias")
    res = await db.execute(
        select(Familia).options(selectinload(Familia.integrantes)).where(Familia.usuario_id == usuario.id)
    )
    familia = res.scalar_one_or_none()
    if familia is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La familia no existe")
    return familia


FamiliaActual = Annotated[Familia, Depends(familia_actual)]


def puede_administrar_centro(usuario: Usuario, centro_id: uuid.UUID) -> bool:
    if usuario.rol == Rol.admin:
        return True
    return usuario.rol == Rol.asociacion and usuario.centro_id == centro_id


def exigir_centro(usuario: Usuario, centro_id: uuid.UUID) -> None:
    if not puede_administrar_centro(usuario, centro_id):
        # 404 en lugar de 403 para no confirmar que el recurso existe.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontrado")

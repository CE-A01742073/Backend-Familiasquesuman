"""Mensajería dentro de la plataforma: SOLO familia ↔ asociación. No existe familia ↔ familia
(decisión de diseño por protección de menores). Polling: GET con `desde`."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import DB, UsuarioActual
from app.core.ratelimit import limite_escritura, limite_general
from app.db.base import ahora
from app.models.catalogo import Centro
from app.models.social import Conversacion, Mensaje
from app.models.usuarios import Familia, Rol, Usuario
from app.schemas.comunes import Mensaje as MensajeSimple
from app.schemas.social import ConversacionIn, ConversacionOut, MensajeIn, MensajeOut
from app.services.notificaciones import notificar

router = APIRouter(prefix="/conversaciones", tags=["mensajes"], dependencies=[Depends(limite_general)])


async def _mi_familia(db: AsyncSession, usuario: Usuario) -> Familia | None:
    if usuario.rol != Rol.familia:
        return None
    return await db.scalar(select(Familia).where(Familia.usuario_id == usuario.id))


async def _conversacion_mia(db: AsyncSession, usuario: Usuario, conversacion_id: uuid.UUID) -> Conversacion:
    c = await db.get(Conversacion, conversacion_id)
    if c is None:
        raise HTTPException(404, "Conversación no encontrada")
    if usuario.rol == Rol.familia:
        fam = await _mi_familia(db, usuario)
        if fam is None or c.familia_id != fam.id:
            raise HTTPException(404, "Conversación no encontrada")
    elif usuario.rol == Rol.asociacion:
        if usuario.centro_id != c.centro_id:
            raise HTTPException(404, "Conversación no encontrada")
    # admin: puede ver todas (moderación)
    return c


def _rol_emisor(usuario: Usuario) -> str:
    return "familia" if usuario.rol == Rol.familia else "asociacion"


async def conversacion_out(db: AsyncSession, c: Conversacion, usuario: Usuario) -> ConversacionOut:
    o = ConversacionOut.model_validate(c)
    fam = await db.get(Familia, c.familia_id)
    cen = await db.get(Centro, c.centro_id)
    o.familia_nombre = fam.nombre if fam else None
    o.centro_nombre = cen.nombre if cen else None
    o.no_leidos = int(
        await db.scalar(
            select(func.count()).select_from(Mensaje).where(
                Mensaje.conversacion_id == c.id, Mensaje.leido.is_(False), Mensaje.emisor_rol != _rol_emisor(usuario)
            )
        ) or 0
    )
    ultimo = await db.scalar(select(Mensaje).where(Mensaje.conversacion_id == c.id).order_by(Mensaje.creado_en.desc()).limit(1))
    if ultimo:
        o.ultimo_mensaje = mensaje_out(ultimo, usuario)
    return o


def mensaje_out(m: Mensaje, usuario: Usuario) -> MensajeOut:
    o = MensajeOut.model_validate(m)
    o.es_mio = m.emisor_id == usuario.id
    return o


@router.get("", response_model=list[ConversacionOut])
async def mis_conversaciones(usuario: UsuarioActual, db: DB):
    if usuario.rol == Rol.familia:
        fam = await _mi_familia(db, usuario)
        cond = [Conversacion.familia_id == (fam.id if fam else None)]
    elif usuario.rol == Rol.asociacion:
        if usuario.centro_id is None:
            return []
        cond = [Conversacion.centro_id == usuario.centro_id]
    else:
        cond = []
    res = await db.execute(select(Conversacion).where(*cond).order_by(Conversacion.actualizado_en.desc()).limit(100))
    return [await conversacion_out(db, c, usuario) for c in res.scalars().all()]


@router.post("", response_model=ConversacionOut, status_code=201, dependencies=[Depends(limite_escritura)])
async def iniciar(datos: ConversacionIn, usuario: UsuarioActual, db: DB):
    """La familia inicia la conversación con un centro verificado."""
    fam = await _mi_familia(db, usuario)
    if fam is None:
        raise HTTPException(403, "Solo las familias inician conversaciones")
    centro = await db.get(Centro, datos.centro_id)
    if centro is None or not centro.activo or not centro.verificado:
        raise HTTPException(404, "Centro no encontrado")
    c = await db.scalar(select(Conversacion).where(Conversacion.familia_id == fam.id, Conversacion.centro_id == centro.id))
    if c is None:
        c = Conversacion(familia_id=fam.id, centro_id=centro.id)
        db.add(c)
        await db.flush()
    if c.bloqueada:
        raise HTTPException(403, "Esta conversación fue bloqueada")
    await _enviar(db, c, usuario, datos.texto)
    return await conversacion_out(db, c, usuario)


async def _enviar(db: AsyncSession, c: Conversacion, usuario: Usuario, texto: str) -> Mensaje:
    m = Mensaje(conversacion_id=c.id, emisor_id=usuario.id, emisor_rol=_rol_emisor(usuario), texto=texto.strip(), creado_en=ahora())
    db.add(m)
    c.actualizado_en = ahora()
    # Notificar al otro lado
    if usuario.rol == Rol.familia:
        res = await db.execute(select(Usuario.id).where(Usuario.centro_id == c.centro_id, Usuario.rol == Rol.asociacion, Usuario.activo.is_(True)))
        destinatarios = [r[0] for r in res.all()]
    else:
        fam = await db.get(Familia, c.familia_id)
        destinatarios = [fam.usuario_id] if fam else []
    for d in destinatarios:
        notificar(db, d, "Nuevo mensaje", texto.strip()[:120], "mensaje", c.id)
    await db.flush()
    return m


@router.get("/{conversacion_id}/mensajes", response_model=list[MensajeOut])
async def mensajes(
    conversacion_id: uuid.UUID, usuario: UsuarioActual, db: DB,
    desde: datetime | None = None, limit: int = Query(50, ge=1, le=200),
):
    c = await _conversacion_mia(db, usuario, conversacion_id)
    cond = [Mensaje.conversacion_id == c.id]
    if desde:
        cond.append(Mensaje.creado_en > desde)
    res = await db.execute(select(Mensaje).where(*cond).order_by(Mensaje.creado_en.desc()).limit(limit))
    items = list(reversed(res.scalars().all()))
    # Marcar como leídos los del otro lado
    for m in items:
        if m.emisor_rol != _rol_emisor(usuario) and not m.leido and usuario.rol != Rol.admin:
            m.leido = True
    return [mensaje_out(m, usuario) for m in items]


@router.post("/{conversacion_id}/mensajes", response_model=MensajeOut, status_code=201, dependencies=[Depends(limite_escritura)])
async def enviar(conversacion_id: uuid.UUID, datos: MensajeIn, usuario: UsuarioActual, db: DB):
    if usuario.rol == Rol.admin:
        raise HTTPException(403, "El administrador solo supervisa conversaciones")
    c = await _conversacion_mia(db, usuario, conversacion_id)
    if c.bloqueada:
        raise HTTPException(403, "Esta conversación fue bloqueada")
    m = await _enviar(db, c, usuario, datos.texto)
    return mensaje_out(m, usuario)


@router.post("/{conversacion_id}/bloquear", response_model=MensajeSimple, dependencies=[Depends(limite_escritura)])
async def bloquear(conversacion_id: uuid.UUID, usuario: UsuarioActual, db: DB):
    """Cualquiera de las dos partes (o admin) puede bloquear; la familia conserva el control."""
    c = await _conversacion_mia(db, usuario, conversacion_id)
    c.bloqueada = True
    return MensajeSimple(mensaje="Conversación bloqueada")

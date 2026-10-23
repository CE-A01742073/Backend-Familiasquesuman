"""Likes y comentarios. Los comentarios se moderan antes de ser visibles (menores en la plataforma)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import auditar
from app.core.deps import DB, Admin, UsuarioActual
from app.core.ratelimit import ip_cliente, limite_escritura, limite_general
from app.db.base import ahora
from app.models.catalogo import Actividad, Campana, Proyecto
from app.models.participacion import EstadoModeracion, Testimonio
from app.models.social import Comentario, Like, Reporte, TipoObjetivo
from app.models.usuarios import Rol
from app.schemas.comunes import Mensaje, Pagina
from app.schemas.participacion import ModeracionIn
from app.schemas.social import ComentarioIn, ComentarioOut, LikeOut, ReporteIn
from app.services.comunes import likes_de
from app.services.notificaciones import notificar

router = APIRouter(tags=["social"], dependencies=[Depends(limite_general)])

_MODELOS = {
    TipoObjetivo.actividad: Actividad,
    TipoObjetivo.campana: Campana,
    TipoObjetivo.proyecto: Proyecto,
    TipoObjetivo.testimonio: Testimonio,
}


async def _existe(db: AsyncSession, tipo: TipoObjetivo, oid: uuid.UUID) -> None:
    obj = await db.get(_MODELOS[tipo], oid)
    if obj is None or (tipo == TipoObjetivo.testimonio and obj.estado != EstadoModeracion.aprobado):
        raise HTTPException(404, "No encontrado")


def comentario_out(c: Comentario, usuario_id: uuid.UUID) -> ComentarioOut:
    o = ComentarioOut.model_validate(c)
    o.autor_nombre = c.usuario.nombre if c.usuario else "Usuario"
    o.es_mio = c.usuario_id == usuario_id
    return o


# ---------- Likes ----------

@router.put("/likes/{tipo}/{objetivo_id}", response_model=LikeOut, dependencies=[Depends(limite_escritura)])
async def dar_like(tipo: TipoObjetivo, objetivo_id: uuid.UUID, usuario: UsuarioActual, db: DB):
    await _existe(db, tipo, objetivo_id)
    existente = await db.get(Like, (usuario.id, tipo, objetivo_id))
    if existente is None:
        db.add(Like(usuario_id=usuario.id, objetivo_tipo=tipo, objetivo_id=objetivo_id, creado_en=ahora()))
        await db.flush()
    conteo = (await likes_de(db, tipo, [objetivo_id], usuario.id))[objetivo_id]
    return LikeOut(objetivo_tipo=tipo, objetivo_id=objetivo_id, likes=conteo[0], me_gusta=True)


@router.delete("/likes/{tipo}/{objetivo_id}", response_model=LikeOut, dependencies=[Depends(limite_escritura)])
async def quitar_like(tipo: TipoObjetivo, objetivo_id: uuid.UUID, usuario: UsuarioActual, db: DB):
    existente = await db.get(Like, (usuario.id, tipo, objetivo_id))
    if existente is not None:
        await db.delete(existente)
        await db.flush()
    conteo = (await likes_de(db, tipo, [objetivo_id], usuario.id))[objetivo_id]
    return LikeOut(objetivo_tipo=tipo, objetivo_id=objetivo_id, likes=conteo[0], me_gusta=False)


# ---------- Comentarios ----------

@router.get("/comentarios/{tipo}/{objetivo_id}", response_model=Pagina[ComentarioOut])
async def comentarios(
    tipo: TipoObjetivo, objetivo_id: uuid.UUID, usuario: UsuarioActual, db: DB,
    limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
):
    """Aprobados para todos; los propios pendientes/rechazados también se ven (con su estado)."""
    cond = [
        Comentario.objetivo_tipo == tipo, Comentario.objetivo_id == objetivo_id,
        (Comentario.estado == EstadoModeracion.aprobado) | (Comentario.usuario_id == usuario.id),
    ]
    total = await db.scalar(select(func.count()).select_from(Comentario).where(*cond))
    res = await db.execute(
        select(Comentario).options(selectinload(Comentario.usuario)).where(*cond)
        .order_by(Comentario.creado_en.desc()).limit(limit).offset(offset)
    )
    return Pagina(items=[comentario_out(c, usuario.id) for c in res.scalars().all()], total=int(total or 0), limit=limit, offset=offset)


@router.post("/comentarios/{tipo}/{objetivo_id}", response_model=ComentarioOut, status_code=201, dependencies=[Depends(limite_escritura)])
async def comentar(tipo: TipoObjetivo, objetivo_id: uuid.UUID, datos: ComentarioIn, usuario: UsuarioActual, db: DB):
    await _existe(db, tipo, objetivo_id)
    # Admin y asociaciones publican directo; las familias pasan por moderación.
    estado = EstadoModeracion.aprobado if usuario.rol in (Rol.admin, Rol.asociacion) else EstadoModeracion.pendiente
    c = Comentario(usuario_id=usuario.id, objetivo_tipo=tipo, objetivo_id=objetivo_id, texto=datos.texto, estado=estado)
    db.add(c)
    await db.flush()
    c = await db.scalar(select(Comentario).options(selectinload(Comentario.usuario)).where(Comentario.id == c.id))
    return comentario_out(c, usuario.id)


@router.delete("/comentarios/{comentario_id}", response_model=Mensaje, dependencies=[Depends(limite_escritura)])
async def borrar_comentario(comentario_id: uuid.UUID, usuario: UsuarioActual, db: DB):
    c = await db.get(Comentario, comentario_id)
    if c is None or (c.usuario_id != usuario.id and usuario.rol != Rol.admin):
        raise HTTPException(404, "Comentario no encontrado")
    await db.delete(c)
    return Mensaje(mensaje="Comentario eliminado")


@router.get("/admin/comentarios", response_model=Pagina[ComentarioOut])
async def comentarios_pendientes(
    db: DB, admin: Admin, estado: EstadoModeracion = EstadoModeracion.pendiente,
    limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
):
    cond = [Comentario.estado == estado]
    total = await db.scalar(select(func.count()).select_from(Comentario).where(*cond))
    res = await db.execute(
        select(Comentario).options(selectinload(Comentario.usuario)).where(*cond)
        .order_by(Comentario.creado_en).limit(limit).offset(offset)
    )
    return Pagina(items=[comentario_out(c, admin.id) for c in res.scalars().all()], total=int(total or 0), limit=limit, offset=offset)


@router.post("/admin/comentarios/{comentario_id}/moderar", response_model=ComentarioOut, dependencies=[Depends(limite_escritura)])
async def moderar_comentario(comentario_id: uuid.UUID, datos: ModeracionIn, admin: Admin, request: Request, db: DB):
    c = await db.scalar(select(Comentario).options(selectinload(Comentario.usuario)).where(Comentario.id == comentario_id))
    if c is None:
        raise HTTPException(404, "Comentario no encontrado")
    c.estado = EstadoModeracion.aprobado if datos.aprobar else EstadoModeracion.rechazado
    c.moderado_por = admin.id
    if not datos.aprobar:
        notificar(db, c.usuario_id, "Comentario no publicado", datos.motivo or "Tu comentario no cumple los lineamientos.", "comentario", c.id)
    await auditar(db, "comentario_moderado", usuario_id=admin.id, objetivo=str(c.id), ip=ip_cliente(request), detalle=c.estado.value)
    return comentario_out(c, admin.id)


# ---------- Reportes ----------

@router.post("/reportes", response_model=Mensaje, status_code=201, dependencies=[Depends(limite_escritura)])
async def reportar(datos: ReporteIn, usuario: UsuarioActual, db: DB):
    db.add(Reporte(usuario_id=usuario.id, objetivo_tipo=datos.objetivo_tipo, objetivo_id=datos.objetivo_id, motivo=datos.motivo, creado_en=ahora()))
    return Mensaje(mensaje="Gracias, el equipo revisará el reporte")


@router.get("/admin/reportes")
async def reportes(db: DB, _: Admin, atendidos: bool = False):
    res = await db.execute(select(Reporte).where(Reporte.atendido.is_(atendidos)).order_by(Reporte.creado_en).limit(200))
    return [
        {"id": r.id, "objetivo_tipo": r.objetivo_tipo, "objetivo_id": r.objetivo_id, "motivo": r.motivo, "creado_en": r.creado_en}
        for r in res.scalars().all()
    ]


@router.post("/admin/reportes/{reporte_id}/atendido", response_model=Mensaje)
async def atender_reporte(reporte_id: uuid.UUID, db: DB, _: Admin):
    r = await db.get(Reporte, reporte_id)
    if r is None:
        raise HTTPException(404, "Reporte no encontrado")
    r.atendido = True
    return Mensaje(mensaje="Reporte atendido")

"""Testimonios con foto (RF-12): nada se publica sin aprobación de Familias que Suman."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core import storage
from app.core.audit import auditar
from app.core.deps import DB, Admin, FamiliaActual, UsuarioActual
from app.core.ratelimit import ip_cliente, limite_escritura, limite_general
from app.db.base import ahora
from app.models.participacion import EstadoInscripcion, EstadoModeracion, Inscripcion, Testimonio
from app.models.social import TipoObjetivo
from app.models.usuarios import Familia
from app.routers.me import _leer_imagen
from app.schemas.comunes import Mensaje, Pagina
from app.schemas.participacion import ModeracionIn, TestimonioOut
from app.services.comunes import likes_de, url_imagen
from app.services.notificaciones import notificar

router = APIRouter(tags=["testimonios"], dependencies=[Depends(limite_general)])


def testimonio_out(t: Testimonio, likes=(0, False), con_foto: bool = True) -> TestimonioOut:
    o = TestimonioOut.model_validate(t)
    o.foto_url = url_imagen(t.foto_key) if con_foto else None
    o.likes, o.me_gusta = likes
    o.familia_nombre = t.familia.nombre if t.familia else None
    o.actividad_titulo = t.actividad.titulo if t.actividad else None
    return o


_opts = (selectinload(Testimonio.familia), selectinload(Testimonio.actividad))


@router.get("/testimonios", response_model=Pagina[TestimonioOut])
async def publicados(
    db: DB, usuario: UsuarioActual, actividad_id: uuid.UUID | None = None,
    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
):
    """Sección 'Nuestras familias': SOLO testimonios aprobados."""
    cond = [Testimonio.estado == EstadoModeracion.aprobado]
    if actividad_id:
        cond.append(Testimonio.actividad_id == actividad_id)
    total = await db.scalar(select(func.count()).select_from(Testimonio).where(*cond))
    res = await db.execute(select(Testimonio).options(*_opts).where(*cond).order_by(Testimonio.moderado_en.desc()).limit(limit).offset(offset))
    items = res.scalars().all()
    likes = await likes_de(db, TipoObjetivo.testimonio, [t.id for t in items], usuario.id)
    return Pagina(items=[testimonio_out(t, likes.get(t.id, (0, False))) for t in items], total=int(total or 0), limit=limit, offset=offset)


@router.get("/me/testimonios", response_model=list[TestimonioOut])
async def mios(familia: FamiliaActual, db: DB):
    res = await db.execute(
        select(Testimonio).options(*_opts).where(Testimonio.familia_id == familia.id).order_by(Testimonio.creado_en.desc())
    )
    return [testimonio_out(t) for t in res.scalars().all()]


@router.post("/me/testimonios", response_model=TestimonioOut, status_code=201, dependencies=[Depends(limite_escritura)])
async def crear(
    familia: FamiliaActual,
    request: Request,
    db: DB,
    actividad_id: Annotated[uuid.UUID, Form()],
    texto: Annotated[str, Form(min_length=10, max_length=600)],
    foto: UploadFile | None = None,
):
    """Solo después de haber participado (inscripción con asistencia o fecha pasada)."""
    ins = await db.scalar(
        select(Inscripcion).options(selectinload(Inscripcion.actividad)).where(
            Inscripcion.familia_id == familia.id, Inscripcion.actividad_id == actividad_id,
            Inscripcion.estado.in_([EstadoInscripcion.confirmada, EstadoInscripcion.asistio]),
        )
    )
    from datetime import date

    if ins is None or (ins.estado == EstadoInscripcion.confirmada and ins.actividad.fecha > date.today()):
        raise HTTPException(409, "Solo puedes compartir un testimonio de actividades en las que ya participaste")
    pendientes = await db.scalar(
        select(func.count()).select_from(Testimonio).where(
            Testimonio.familia_id == familia.id, Testimonio.actividad_id == actividad_id,
            Testimonio.estado != EstadoModeracion.rechazado,
        )
    )
    if pendientes:
        raise HTTPException(409, "Ya enviaste un testimonio de esta actividad")

    key = None
    if foto is not None and foto.filename:
        datos = await _leer_imagen(foto)
        key = storage.nueva_key("testimonios")
        await storage.guardar(key, datos)

    t = Testimonio(familia_id=familia.id, actividad_id=actividad_id, texto=texto.strip(), foto_key=key)
    db.add(t)
    await db.flush()
    await auditar(db, "testimonio_enviado", usuario_id=familia.usuario_id, objetivo=str(t.id), ip=ip_cliente(request))
    t = await db.scalar(select(Testimonio).options(*_opts).where(Testimonio.id == t.id))
    return testimonio_out(t)


@router.delete("/me/testimonios/{testimonio_id}", response_model=Mensaje, dependencies=[Depends(limite_escritura)])
async def borrar_mio(testimonio_id: uuid.UUID, familia: FamiliaActual, db: DB):
    t = await db.scalar(select(Testimonio).where(Testimonio.id == testimonio_id, Testimonio.familia_id == familia.id))
    if t is None:
        raise HTTPException(404, "Testimonio no encontrado")
    if t.foto_key:
        await storage.borrar(t.foto_key)
    await db.delete(t)
    return Mensaje(mensaje="Testimonio eliminado")


# ---------- Moderación (admin) ----------

@router.get("/admin/testimonios", response_model=Pagina[TestimonioOut])
async def pendientes(
    db: DB, _: Admin, estado: EstadoModeracion = EstadoModeracion.pendiente,
    limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0),
):
    cond = [Testimonio.estado == estado]
    total = await db.scalar(select(func.count()).select_from(Testimonio).where(*cond))
    res = await db.execute(select(Testimonio).options(*_opts).where(*cond).order_by(Testimonio.creado_en).limit(limit).offset(offset))
    return Pagina(items=[testimonio_out(t) for t in res.scalars().all()], total=int(total or 0), limit=limit, offset=offset)


@router.post("/admin/testimonios/{testimonio_id}/moderar", response_model=TestimonioOut, dependencies=[Depends(limite_escritura)])
async def moderar(testimonio_id: uuid.UUID, datos: ModeracionIn, admin: Admin, request: Request, db: DB):
    t = await db.scalar(select(Testimonio).options(*_opts).where(Testimonio.id == testimonio_id))
    if t is None:
        raise HTTPException(404, "Testimonio no encontrado")
    t.estado = EstadoModeracion.aprobado if datos.aprobar else EstadoModeracion.rechazado
    t.motivo_rechazo = None if datos.aprobar else (datos.motivo or "No cumple los lineamientos de publicación")
    t.moderado_por, t.moderado_en = admin.id, ahora()
    fam = await db.get(Familia, t.familia_id)
    if fam:
        notificar(
            db, fam.usuario_id,
            "Testimonio publicado" if datos.aprobar else "Testimonio no publicado",
            "Gracias por compartir: tu testimonio ya aparece en 'Nuestras familias'." if datos.aprobar
            else f"Tu testimonio no fue publicado. Motivo: {t.motivo_rechazo}",
            "testimonio", t.id,
        )
    await auditar(db, "testimonio_moderado", usuario_id=admin.id, objetivo=str(t.id), ip=ip_cliente(request), detalle=t.estado.value)
    return testimonio_out(t)

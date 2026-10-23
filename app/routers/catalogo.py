"""Catálogo público (requiere sesión): ciudades, centros, actividades, campañas, proyectos, aviso de privacidad.
RF-01, RF-02, RF-03, RF-04, RF-05, RF-09, RF-10, RF-15, RF-19."""
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import DB, UsuarioActual
from app.core.ratelimit import limite_general
from app.db.base import ahora
from app.models.catalogo import Actividad, AvisoPrivacidad, Campana, Categoria, Centro, Ciudad, EstadoActividad, Proyecto
from app.models.participacion import Donacion
from app.models.social import TipoObjetivo
from app.models.usuarios import Familia, Rol, Usuario
from app.schemas.catalogo import ActividadOut, AvisoOut, CampanaOut, CentroOut, CiudadOut, ProyectoOut
from app.schemas.comunes import Pagina
from app.services.comunes import likes_de, url_imagen

router = APIRouter(tags=["catalogo"], dependencies=[Depends(limite_general)])


async def ciudad_por_clave(db: AsyncSession, clave: str) -> Ciudad:
    c = await db.scalar(select(Ciudad).where(Ciudad.clave == clave.lower(), Ciudad.activa.is_(True)))
    if c is None:
        raise HTTPException(404, "Ciudad no encontrada")
    return c


async def ciudad_de_usuario(db: AsyncSession, usuario: Usuario, ciudad: str | None) -> Ciudad | None:
    """RF-02: si no se manda ciudad, se usa la de la familia."""
    if ciudad:
        return await ciudad_por_clave(db, ciudad)
    if usuario.rol == Rol.familia:
        fam = await db.scalar(select(Familia).where(Familia.usuario_id == usuario.id))
        if fam and fam.ciudad_id:
            return await db.get(Ciudad, fam.ciudad_id)
    return None


def centro_out(c: Centro) -> CentroOut:
    o = CentroOut.model_validate(c)
    o.imagen_url = url_imagen(c.imagen_key)
    return o


def actividad_out(a: Actividad, likes: tuple[int, bool] = (0, False), centro_nombre: str | None = None) -> ActividadOut:
    o = ActividadOut.model_validate(a)
    o.cupos_disponibles = max(a.cupos_totales - a.cupos_ocupados, 0)
    o.imagen_url = url_imagen(a.imagen_key)
    o.likes, o.me_gusta = likes
    o.centro_nombre = centro_nombre or (a.centro.nombre if a.centro else None)
    return o


def campana_out(c: Campana, likes=(0, False), ya_apoye: bool = False) -> CampanaOut:
    o = CampanaOut.model_validate(c)
    o.imagen_url = url_imagen(c.imagen_key)
    o.likes, o.me_gusta = likes
    o.ya_apoye = ya_apoye
    o.centro_nombre = c.centro.nombre if c.centro else None
    return o


def proyecto_out(p: Proyecto, likes=(0, False)) -> ProyectoOut:
    o = ProyectoOut.model_validate(p)
    o.imagen_url = url_imagen(p.imagen_key)
    o.likes, o.me_gusta = likes
    o.centro_nombre = p.centro.nombre if p.centro else None
    return o


@router.get("/ciudades", response_model=list[CiudadOut])
async def ciudades(db: DB, _: UsuarioActual):
    res = await db.execute(select(Ciudad).where(Ciudad.activa.is_(True)).order_by(Ciudad.nombre))
    return res.scalars().all()


@router.get("/centros", response_model=Pagina[CentroOut])
async def centros(
    db: DB,
    usuario: UsuarioActual,
    ciudad: str | None = None,
    categoria: Categoria | None = None,
    q: str | None = Query(None, max_length=60),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """RF-01: directorio de asociaciones verificadas por categoría."""
    c = await ciudad_de_usuario(db, usuario, ciudad)
    cond = [Centro.activo.is_(True), Centro.verificado.is_(True)]
    if c:
        cond.append(Centro.ciudad_id == c.id)
    if categoria:
        cond.append(Centro.categoria == categoria)
    if q:
        cond.append(Centro.nombre.ilike(f"%{q}%"))  # parámetro ligado: sin inyección
    total = await db.scalar(select(func.count()).select_from(Centro).where(*cond))
    res = await db.execute(select(Centro).where(*cond).order_by(Centro.nombre).limit(limit).offset(offset))
    return Pagina(items=[centro_out(x) for x in res.scalars().all()], total=int(total or 0), limit=limit, offset=offset)


@router.get("/centros/{centro_id}", response_model=CentroOut)
async def centro(centro_id: uuid.UUID, db: DB, _: UsuarioActual):
    c = await db.get(Centro, centro_id)
    if c is None or not c.activo:
        raise HTTPException(404, "Centro no encontrado")
    return centro_out(c)


@router.get("/centros/{centro_id}/actividades", response_model=list[ActividadOut])
async def actividades_de_centro(centro_id: uuid.UUID, db: DB, usuario: UsuarioActual):
    res = await db.execute(
        select(Actividad)
        .options(selectinload(Actividad.centro))
        .where(Actividad.centro_id == centro_id, Actividad.estado == EstadoActividad.activa, Actividad.fecha >= date.today())
        .order_by(Actividad.fecha, Actividad.hora_inicio)
    )
    items = res.scalars().all()
    likes = await likes_de(db, TipoObjetivo.actividad, [a.id for a in items], usuario.id)
    return [actividad_out(a, likes.get(a.id, (0, False))) for a in items]


@router.get("/actividades", response_model=Pagina[ActividadOut])
async def actividades(
    db: DB,
    usuario: UsuarioActual,
    ciudad: str | None = None,
    categoria: Categoria | None = None,
    solo_con_cupo: bool = False,
    apta_ninos: bool | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    q: str | None = Query(None, max_length=60),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """RF-04 / RF-05: actividades con cupos al momento."""
    c = await ciudad_de_usuario(db, usuario, ciudad)
    cond = [Actividad.estado == EstadoActividad.activa, Actividad.fecha >= (desde or date.today())]
    if c:
        cond.append(Actividad.ciudad_id == c.id)
    if categoria:
        cond.append(Actividad.categoria == categoria)
    if solo_con_cupo:
        cond.append(Actividad.cupos_ocupados < Actividad.cupos_totales)
    if apta_ninos is not None:
        cond.append(Actividad.apta_ninos.is_(apta_ninos))
    if hasta:
        cond.append(Actividad.fecha <= hasta)
    if q:
        cond.append(Actividad.titulo.ilike(f"%{q}%"))
    total = await db.scalar(select(func.count()).select_from(Actividad).where(*cond))
    res = await db.execute(
        select(Actividad).options(selectinload(Actividad.centro)).where(*cond)
        .order_by(Actividad.fecha, Actividad.hora_inicio).limit(limit).offset(offset)
    )
    items = res.scalars().all()
    likes = await likes_de(db, TipoObjetivo.actividad, [a.id for a in items], usuario.id)
    return Pagina(items=[actividad_out(a, likes.get(a.id, (0, False))) for a in items], total=int(total or 0), limit=limit, offset=offset)


@router.get("/actividades/{actividad_id}", response_model=ActividadOut)
async def actividad(actividad_id: uuid.UUID, db: DB, usuario: UsuarioActual):
    a = await db.scalar(select(Actividad).options(selectinload(Actividad.centro)).where(Actividad.id == actividad_id))
    if a is None:
        raise HTTPException(404, "Actividad no encontrada")
    likes = await likes_de(db, TipoObjetivo.actividad, [a.id], usuario.id)
    return actividad_out(a, likes.get(a.id, (0, False)))


@router.get("/campanas", response_model=Pagina[CampanaOut])
async def campanas(
    db: DB,
    usuario: UsuarioActual,
    ciudad: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """RF-09 / RF-10: campañas vigentes con qué llevar y dónde."""
    c = await ciudad_de_usuario(db, usuario, ciudad)
    cond = [Campana.activa.is_(True)]
    if c:
        cond.append(Campana.ciudad_id == c.id)
    total = await db.scalar(select(func.count()).select_from(Campana).where(*cond))
    res = await db.execute(
        select(Campana).options(selectinload(Campana.centro)).where(*cond).order_by(Campana.hasta.nulls_last(), Campana.titulo)
        .limit(limit).offset(offset)
    )
    items = res.scalars().all()
    likes = await likes_de(db, TipoObjetivo.campana, [x.id for x in items], usuario.id)
    apoyadas: set[uuid.UUID] = set()
    if usuario.rol == Rol.familia:
        fam = await db.scalar(select(Familia).where(Familia.usuario_id == usuario.id))
        if fam:
            r = await db.execute(select(Donacion.campana_id).where(Donacion.familia_id == fam.id, Donacion.campana_id.is_not(None)))
            apoyadas = {x[0] for x in r.all()}
    return Pagina(
        items=[campana_out(x, likes.get(x.id, (0, False)), x.id in apoyadas) for x in items],
        total=int(total or 0), limit=limit, offset=offset,
    )


@router.get("/campanas/{campana_id}", response_model=CampanaOut)
async def campana(campana_id: uuid.UUID, db: DB, usuario: UsuarioActual):
    c = await db.scalar(select(Campana).options(selectinload(Campana.centro)).where(Campana.id == campana_id))
    if c is None:
        raise HTTPException(404, "Campaña no encontrada")
    likes = await likes_de(db, TipoObjetivo.campana, [c.id], usuario.id)
    return campana_out(c, likes.get(c.id, (0, False)))


@router.get("/proyectos", response_model=Pagina[ProyectoOut])
async def proyectos(
    db: DB,
    usuario: UsuarioActual,
    orden: str = Query("recientes", pattern=r"^(recientes|actualizados|titulo)$"),
    desde: datetime | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """RF-09 / RF-19: proyectos vigentes, filtrables por fecha de creación o actualización."""
    cond = [Proyecto.activo.is_(True)]
    if desde:
        cond.append((Proyecto.actualizado_en >= desde) if orden == "actualizados" else (Proyecto.creado_en >= desde))
    orden_sql = {
        "recientes": Proyecto.creado_en.desc(),
        "actualizados": Proyecto.actualizado_en.desc(),
        "titulo": Proyecto.titulo.asc(),
    }[orden]
    total = await db.scalar(select(func.count()).select_from(Proyecto).where(*cond))
    res = await db.execute(
        select(Proyecto).options(selectinload(Proyecto.centro)).where(*cond).order_by(orden_sql).limit(limit).offset(offset)
    )
    items = res.scalars().all()
    likes = await likes_de(db, TipoObjetivo.proyecto, [x.id for x in items], usuario.id)
    return Pagina(items=[proyecto_out(x, likes.get(x.id, (0, False))) for x in items], total=int(total or 0), limit=limit, offset=offset)


@router.get("/proyectos/{proyecto_id}", response_model=ProyectoOut)
async def proyecto(proyecto_id: uuid.UUID, db: DB, usuario: UsuarioActual):
    p = await db.scalar(select(Proyecto).options(selectinload(Proyecto.centro)).where(Proyecto.id == proyecto_id))
    if p is None:
        raise HTTPException(404, "Proyecto no encontrado")
    likes = await likes_de(db, TipoObjetivo.proyecto, [p.id], usuario.id)
    return proyecto_out(p, likes.get(p.id, (0, False)))


@router.get("/aviso-privacidad", response_model=AvisoOut)
async def aviso_privacidad(db: DB):
    """RF-15. Público (sin sesión): debe poder leerse ANTES de registrarse."""
    a = await db.scalar(select(AvisoPrivacidad).order_by(AvisoPrivacidad.publicado_en.desc()).limit(1))
    if a is None:
        raise HTTPException(404, "Aviso no publicado")
    return a


@router.get("/sync")
async def sync(
    db: DB,
    usuario: UsuarioActual,
    ciudad: str | None = None,
    desde: datetime | None = None,
):
    """Para la caché offline (Room): regresa lo que cambió desde `desde` en la ciudad.
    Incluye registros inactivos/cancelados para que la app los retire de su caché."""
    c = await ciudad_de_usuario(db, usuario, ciudad)
    marca = ahora()

    def _cond(modelo, con_ciudad: bool = True):
        cond = []
        if desde:
            cond.append(modelo.actualizado_en > desde)
        if c and con_ciudad:
            cond.append(modelo.ciudad_id == c.id)
        return cond

    centros_ = (await db.execute(select(Centro).where(*_cond(Centro)))).scalars().all()
    acts = (await db.execute(select(Actividad).options(selectinload(Actividad.centro)).where(*_cond(Actividad)))).scalars().all()
    camps = (await db.execute(select(Campana).options(selectinload(Campana.centro)).where(*_cond(Campana)))).scalars().all()
    proys = (await db.execute(select(Proyecto).options(selectinload(Proyecto.centro)).where(*_cond(Proyecto, False)))).scalars().all()
    return {
        "marca": marca,
        "ciudad": c.clave if c else None,
        "centros": [centro_out(x) for x in centros_],
        "actividades": [actividad_out(x) for x in acts],
        "campanas": [campana_out(x) for x in camps],
        "proyectos": [proyecto_out(x) for x in proys],
    }

"""Gestión para asociaciones (su propio centro) y administradores (todo).
La autorización se verifica en CADA endpoint contra la BD, nunca solo con el rol del token."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import storage
from app.core.audit import auditar
from app.core.deps import DB, Admin, Asociacion, exigir_centro
from app.core.ratelimit import ip_cliente, limite_escritura, limite_general
from app.models.catalogo import Actividad, Campana, Centro, Ciudad, EstadoActividad, Proyecto
from app.models.participacion import EstadoInscripcion, Inscripcion
from app.models.usuarios import AuditLog, Familia, Rol, Usuario
from app.routers.catalogo import actividad_out, campana_out, centro_out, ciudad_por_clave, proyecto_out
from app.routers.me import _leer_imagen
from app.schemas.catalogo import (
    ActividadIn,
    ActividadOut,
    ActividadPatch,
    CampanaIn,
    CampanaOut,
    CampanaPatch,
    CentroIn,
    CentroOut,
    CentroPatch,
    ProyectoIn,
    ProyectoOut,
    ProyectoPatch,
)
from app.schemas.comunes import Mensaje, Pagina
from app.schemas.participacion import AsistenciaIn, AsistenteListaOut, AsistenteOut
from app.schemas.social import RolIn, UsuarioAdminOut
from app.services.notificaciones import notificar

router = APIRouter(prefix="/gestion", tags=["gestion"], dependencies=[Depends(limite_general)])


def _aplicar(obj, datos, excluir: set[str] = frozenset()) -> None:
    for k, v in datos.model_dump(exclude_unset=True).items():
        if k in excluir:
            continue
        if isinstance(v, list):
            v = [x.value if hasattr(x, "value") else x for x in v]
        setattr(obj, k, v)


async def _centro(db: AsyncSession, usuario: Usuario, centro_id: uuid.UUID) -> Centro:
    exigir_centro(usuario, centro_id)
    c = await db.get(Centro, centro_id)
    if c is None:
        raise HTTPException(404, "No encontrado")
    return c


# ---------- Centros ----------

@router.get("/centros", response_model=list[CentroOut])
async def mis_centros(usuario: Asociacion, db: DB):
    if usuario.rol == Rol.admin:
        res = await db.execute(select(Centro).order_by(Centro.nombre))
        return [centro_out(c) for c in res.scalars().all()]
    if usuario.centro_id is None:
        return []
    c = await db.get(Centro, usuario.centro_id)
    return [centro_out(c)] if c else []


@router.post("/centros", response_model=CentroOut, status_code=201, dependencies=[Depends(limite_escritura)])
async def crear_centro(datos: CentroIn, admin: Admin, request: Request, db: DB):
    ciudad = await ciudad_por_clave(db, datos.ciudad)
    c = Centro(ciudad_id=ciudad.id, verificado=True)
    _aplicar(c, datos, excluir={"ciudad"})
    db.add(c)
    await db.flush()
    await auditar(db, "centro_creado", usuario_id=admin.id, objetivo=str(c.id), ip=ip_cliente(request))
    return centro_out(c)


@router.patch("/centros/{centro_id}", response_model=CentroOut, dependencies=[Depends(limite_escritura)])
async def editar_centro(centro_id: uuid.UUID, datos: CentroPatch, usuario: Asociacion, request: Request, db: DB):
    c = await _centro(db, usuario, centro_id)
    if usuario.rol != Rol.admin and datos.activo is not None:
        raise HTTPException(403, "Solo un administrador activa o desactiva centros")
    _aplicar(c, datos)
    await auditar(db, "centro_editado", usuario_id=usuario.id, objetivo=str(c.id), ip=ip_cliente(request))
    return centro_out(c)


@router.post("/centros/{centro_id}/verificar", response_model=CentroOut, dependencies=[Depends(limite_escritura)])
async def verificar_centro(centro_id: uuid.UUID, admin: Admin, request: Request, db: DB, verificado: bool = True):
    c = await db.get(Centro, centro_id)
    if c is None:
        raise HTTPException(404, "No encontrado")
    c.verificado = verificado
    await auditar(db, "centro_verificado", usuario_id=admin.id, objetivo=str(c.id), ip=ip_cliente(request), detalle=str(verificado))
    return centro_out(c)


@router.put("/centros/{centro_id}/imagen", response_model=CentroOut, dependencies=[Depends(limite_escritura)])
async def imagen_centro(centro_id: uuid.UUID, archivo: UploadFile, usuario: Asociacion, db: DB):
    c = await _centro(db, usuario, centro_id)
    c.imagen_key = await _reemplazar_imagen(archivo, "centros", c.imagen_key)
    return centro_out(c)


async def _reemplazar_imagen(archivo: UploadFile, prefijo: str, anterior: str | None) -> str:
    datos = await _leer_imagen(archivo)
    key = storage.nueva_key(prefijo)
    await storage.guardar(key, datos)
    if anterior:
        await storage.borrar(anterior)
    return key


# ---------- Actividades ----------

@router.get("/centros/{centro_id}/actividades", response_model=list[ActividadOut])
async def actividades_centro(centro_id: uuid.UUID, usuario: Asociacion, db: DB, incluir_pasadas: bool = True):
    await _centro(db, usuario, centro_id)
    res = await db.execute(
        select(Actividad).options(selectinload(Actividad.centro)).where(Actividad.centro_id == centro_id)
        .order_by(Actividad.fecha.desc(), Actividad.hora_inicio)
    )
    return [actividad_out(a) for a in res.scalars().all()]


@router.post("/centros/{centro_id}/actividades", response_model=ActividadOut, status_code=201, dependencies=[Depends(limite_escritura)])
async def crear_actividad(centro_id: uuid.UUID, datos: ActividadIn, usuario: Asociacion, request: Request, db: DB):
    c = await _centro(db, usuario, centro_id)
    a = Actividad(centro_id=c.id, ciudad_id=c.ciudad_id)
    _aplicar(a, datos)
    db.add(a)
    await db.flush()
    a = await db.scalar(select(Actividad).options(selectinload(Actividad.centro)).where(Actividad.id == a.id))
    await auditar(db, "actividad_creada", usuario_id=usuario.id, objetivo=str(a.id), ip=ip_cliente(request))
    return actividad_out(a)


async def _actividad(db: AsyncSession, usuario: Usuario, actividad_id: uuid.UUID) -> Actividad:
    a = await db.scalar(select(Actividad).options(selectinload(Actividad.centro)).where(Actividad.id == actividad_id))
    if a is None:
        raise HTTPException(404, "No encontrado")
    exigir_centro(usuario, a.centro_id)
    return a


@router.patch("/actividades/{actividad_id}", response_model=ActividadOut, dependencies=[Depends(limite_escritura)])
async def editar_actividad(actividad_id: uuid.UUID, datos: ActividadPatch, usuario: Asociacion, request: Request, db: DB):
    a = await _actividad(db, usuario, actividad_id)
    if datos.cupos_totales is not None and datos.cupos_totales < a.cupos_ocupados:
        raise HTTPException(422, f"Ya hay {a.cupos_ocupados} lugares ocupados; no puedes bajar el cupo por debajo")
    estado_previo = a.estado
    _aplicar(a, datos)
    if datos.estado == EstadoActividad.cancelada and estado_previo != EstadoActividad.cancelada:
        res = await db.execute(
            select(Inscripcion).options(selectinload(Inscripcion.familia))
            .where(Inscripcion.actividad_id == a.id, Inscripcion.estado == EstadoInscripcion.confirmada)
        )
        for ins in res.scalars().all():
            ins.estado = EstadoInscripcion.cancelada
            notificar(db, ins.familia.usuario_id, "Actividad cancelada", f"'{a.titulo}' fue cancelada por la asociación.", "actividad", a.id)
        a.cupos_ocupados = 0
    await auditar(db, "actividad_editada", usuario_id=usuario.id, objetivo=str(a.id), ip=ip_cliente(request))
    return actividad_out(a)


@router.delete("/actividades/{actividad_id}", response_model=Mensaje, dependencies=[Depends(limite_escritura)])
async def borrar_actividad(actividad_id: uuid.UUID, usuario: Asociacion, request: Request, db: DB):
    """Borrado real solo si nadie se ha inscrito; si no, se cancela (se conserva el historial)."""
    a = await _actividad(db, usuario, actividad_id)
    inscritos = await db.scalar(select(func.count()).select_from(Inscripcion).where(Inscripcion.actividad_id == a.id))
    if inscritos:
        raise HTTPException(409, "Tiene inscripciones: cancélala con PATCH estado=cancelada en lugar de borrarla")
    if a.imagen_key:
        await storage.borrar(a.imagen_key)
    await db.delete(a)
    await auditar(db, "actividad_borrada", usuario_id=usuario.id, objetivo=str(actividad_id), ip=ip_cliente(request))
    return Mensaje(mensaje="Actividad eliminada")


@router.put("/actividades/{actividad_id}/imagen", response_model=ActividadOut, dependencies=[Depends(limite_escritura)])
async def imagen_actividad(actividad_id: uuid.UUID, archivo: UploadFile, usuario: Asociacion, db: DB):
    a = await _actividad(db, usuario, actividad_id)
    a.imagen_key = await _reemplazar_imagen(archivo, "actividades", a.imagen_key)
    return actividad_out(a)


@router.get("/actividades/{actividad_id}/asistentes", response_model=list[AsistenteListaOut])
async def lista_asistentes(actividad_id: uuid.UUID, usuario: Asociacion, db: DB):
    """RF-06: la asociación recibe la lista de asistentes con nombres y edades."""
    a = await _actividad(db, usuario, actividad_id)
    res = await db.execute(
        select(Inscripcion)
        .options(selectinload(Inscripcion.asistentes), selectinload(Inscripcion.familia).selectinload(Familia.usuario))
        .where(Inscripcion.actividad_id == a.id, Inscripcion.estado != EstadoInscripcion.cancelada)
        .order_by(Inscripcion.creado_en)
    )
    return [
        AsistenteListaOut(
            inscripcion_id=i.id, familia_nombre=i.familia.nombre, contacto_email=i.familia.usuario.email,
            comentario=i.comentario, estado=i.estado, personas=i.personas,
            asistentes=[AsistenteOut.model_validate(x) for x in i.asistentes],
        )
        for i in res.scalars().all()
    ]


@router.post("/actividades/{actividad_id}/asistencia", response_model=Mensaje, dependencies=[Depends(limite_escritura)])
async def marcar_asistencia(actividad_id: uuid.UUID, datos: AsistenciaIn, usuario: Asociacion, request: Request, db: DB):
    """Alimenta el historial e insignias (RF-11, RF-14)."""
    a = await _actividad(db, usuario, actividad_id)
    ids = set(datos.asistieron) | set(datos.no_asistieron)
    res = await db.execute(select(Inscripcion).where(Inscripcion.actividad_id == a.id, Inscripcion.id.in_(ids)))
    encontradas = {i.id: i for i in res.scalars().all()}
    if len(encontradas) != len(ids):
        raise HTTPException(422, "Hay inscripciones que no pertenecen a esta actividad")
    for iid in datos.asistieron:
        encontradas[iid].estado = EstadoInscripcion.asistio
    for iid in datos.no_asistieron:
        encontradas[iid].estado = EstadoInscripcion.no_asistio
    if a.estado == EstadoActividad.activa:
        a.estado = EstadoActividad.finalizada
    await auditar(db, "asistencia_marcada", usuario_id=usuario.id, objetivo=str(a.id), ip=ip_cliente(request))
    return Mensaje(mensaje=f"Asistencia registrada para {len(ids)} inscripciones")


# ---------- Campañas ----------

@router.get("/centros/{centro_id}/campanas", response_model=list[CampanaOut])
async def campanas_centro(centro_id: uuid.UUID, usuario: Asociacion, db: DB):
    """Todas las campañas del centro, activas o no, para editarlas desde la app."""
    await _centro(db, usuario, centro_id)
    res = await db.execute(
        select(Campana).options(selectinload(Campana.centro)).where(Campana.centro_id == centro_id)
        .order_by(Campana.activa.desc(), Campana.actualizado_en.desc())
    )
    return [campana_out(k) for k in res.scalars().all()]


@router.post("/centros/{centro_id}/campanas", response_model=CampanaOut, status_code=201, dependencies=[Depends(limite_escritura)])
async def crear_campana(centro_id: uuid.UUID, datos: CampanaIn, usuario: Asociacion, request: Request, db: DB):
    c = await _centro(db, usuario, centro_id)
    k = Campana(centro_id=c.id, ciudad_id=c.ciudad_id)
    _aplicar(k, datos)
    db.add(k)
    await db.flush()
    k = await db.scalar(select(Campana).options(selectinload(Campana.centro)).where(Campana.id == k.id))
    await auditar(db, "campana_creada", usuario_id=usuario.id, objetivo=str(k.id), ip=ip_cliente(request))
    return campana_out(k)


async def _campana(db: AsyncSession, usuario: Usuario, campana_id: uuid.UUID) -> Campana:
    k = await db.scalar(select(Campana).options(selectinload(Campana.centro)).where(Campana.id == campana_id))
    if k is None:
        raise HTTPException(404, "No encontrado")
    exigir_centro(usuario, k.centro_id)
    return k


@router.patch("/campanas/{campana_id}", response_model=CampanaOut, dependencies=[Depends(limite_escritura)])
async def editar_campana(campana_id: uuid.UUID, datos: CampanaPatch, usuario: Asociacion, request: Request, db: DB):
    k = await _campana(db, usuario, campana_id)
    _aplicar(k, datos)
    await auditar(db, "campana_editada", usuario_id=usuario.id, objetivo=str(k.id), ip=ip_cliente(request))
    return campana_out(k)


@router.put("/campanas/{campana_id}/imagen", response_model=CampanaOut, dependencies=[Depends(limite_escritura)])
async def imagen_campana(campana_id: uuid.UUID, archivo: UploadFile, usuario: Asociacion, db: DB):
    k = await _campana(db, usuario, campana_id)
    k.imagen_key = await _reemplazar_imagen(archivo, "campanas", k.imagen_key)
    return campana_out(k)


# ---------- Proyectos ----------

@router.get("/centros/{centro_id}/proyectos", response_model=list[ProyectoOut])
async def proyectos_centro(centro_id: uuid.UUID, usuario: Asociacion, db: DB):
    await _centro(db, usuario, centro_id)
    res = await db.execute(
        select(Proyecto).options(selectinload(Proyecto.centro)).where(Proyecto.centro_id == centro_id)
        .order_by(Proyecto.activo.desc(), Proyecto.actualizado_en.desc())
    )
    return [proyecto_out(p) for p in res.scalars().all()]


@router.post("/centros/{centro_id}/proyectos", response_model=ProyectoOut, status_code=201, dependencies=[Depends(limite_escritura)])
async def crear_proyecto(centro_id: uuid.UUID, datos: ProyectoIn, usuario: Asociacion, request: Request, db: DB):
    c = await _centro(db, usuario, centro_id)
    p = Proyecto(centro_id=c.id)
    _aplicar(p, datos)
    db.add(p)
    await db.flush()
    p = await db.scalar(select(Proyecto).options(selectinload(Proyecto.centro)).where(Proyecto.id == p.id))
    await auditar(db, "proyecto_creado", usuario_id=usuario.id, objetivo=str(p.id), ip=ip_cliente(request))
    return proyecto_out(p)


async def _proyecto(db: AsyncSession, usuario: Usuario, proyecto_id: uuid.UUID) -> Proyecto:
    p = await db.scalar(select(Proyecto).options(selectinload(Proyecto.centro)).where(Proyecto.id == proyecto_id))
    if p is None:
        raise HTTPException(404, "No encontrado")
    exigir_centro(usuario, p.centro_id)
    return p


@router.patch("/proyectos/{proyecto_id}", response_model=ProyectoOut, dependencies=[Depends(limite_escritura)])
async def editar_proyecto(proyecto_id: uuid.UUID, datos: ProyectoPatch, usuario: Asociacion, request: Request, db: DB):
    p = await _proyecto(db, usuario, proyecto_id)
    _aplicar(p, datos)
    await auditar(db, "proyecto_editado", usuario_id=usuario.id, objetivo=str(p.id), ip=ip_cliente(request))
    return proyecto_out(p)


@router.put("/proyectos/{proyecto_id}/imagen", response_model=ProyectoOut, dependencies=[Depends(limite_escritura)])
async def imagen_proyecto(proyecto_id: uuid.UUID, archivo: UploadFile, usuario: Asociacion, db: DB):
    p = await _proyecto(db, usuario, proyecto_id)
    p.imagen_key = await _reemplazar_imagen(archivo, "proyectos", p.imagen_key)
    return proyecto_out(p)


# ---------- Administración de usuarios (solo admin) ----------

@router.get("/usuarios", response_model=Pagina[UsuarioAdminOut])
async def usuarios(
    db: DB, _: Admin, q: str | None = Query(None, max_length=60), rol: Rol | None = None,
    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
):
    cond = [Usuario.eliminado_en.is_(None)]
    if q:
        cond.append(Usuario.email.ilike(f"%{q}%"))
    if rol:
        cond.append(Usuario.rol == rol)
    total = await db.scalar(select(func.count()).select_from(Usuario).where(*cond))
    res = await db.execute(select(Usuario).where(*cond).order_by(Usuario.creado_en.desc()).limit(limit).offset(offset))
    return Pagina(items=[UsuarioAdminOut.model_validate(u) for u in res.scalars().all()], total=int(total or 0), limit=limit, offset=offset)


@router.patch("/usuarios/{usuario_id}/rol", response_model=UsuarioAdminOut, dependencies=[Depends(limite_escritura)])
async def cambiar_rol(usuario_id: uuid.UUID, datos: RolIn, admin: Admin, request: Request, db: DB):
    """Asigna rol; para `asociacion` se indica el centro que administrará."""
    u = await db.get(Usuario, usuario_id)
    if u is None or u.eliminado_en is not None:
        raise HTTPException(404, "Usuario no encontrado")
    if u.id == admin.id:
        raise HTTPException(422, "No puedes cambiar tu propio rol")
    nuevo = Rol(datos.rol)
    if nuevo == Rol.asociacion:
        if datos.centro_id is None or await db.get(Centro, datos.centro_id) is None:
            raise HTTPException(422, "Indica un centro válido para la asociación")
        u.centro_id = datos.centro_id
    else:
        u.centro_id = None
    u.rol = nuevo
    await auditar(db, "rol_cambiado", usuario_id=admin.id, objetivo=str(u.id), ip=ip_cliente(request), detalle=nuevo.value)
    return UsuarioAdminOut.model_validate(u)


@router.post("/usuarios/{usuario_id}/desbloquear", response_model=Mensaje, dependencies=[Depends(limite_escritura)])
async def desbloquear(usuario_id: uuid.UUID, admin: Admin, request: Request, db: DB):
    await db.execute(update(Usuario).where(Usuario.id == usuario_id).values(bloqueado_hasta=None, intentos_fallidos=0))
    await auditar(db, "usuario_desbloqueado", usuario_id=admin.id, objetivo=str(usuario_id), ip=ip_cliente(request))
    return Mensaje(mensaje="Usuario desbloqueado")


@router.post("/usuarios/{usuario_id}/desactivar", response_model=Mensaje, dependencies=[Depends(limite_escritura)])
async def desactivar(usuario_id: uuid.UUID, admin: Admin, request: Request, db: DB, activo: bool = False):
    if usuario_id == admin.id:
        raise HTTPException(422, "No puedes desactivar tu propia cuenta")
    await db.execute(update(Usuario).where(Usuario.id == usuario_id).values(activo=activo))
    await auditar(db, "usuario_desactivado" if not activo else "usuario_activado", usuario_id=admin.id, objetivo=str(usuario_id), ip=ip_cliente(request))
    return Mensaje(mensaje="Cuenta actualizada")


@router.get("/auditoria")
async def auditoria(db: DB, _: Admin, accion: str | None = Query(None, max_length=60), limit: int = Query(100, ge=1, le=500)):
    cond = []
    if accion:
        cond.append(AuditLog.accion == accion)
    res = await db.execute(select(AuditLog).where(*cond).order_by(AuditLog.creado_en.desc()).limit(limit))
    return [
        {"id": a.id, "usuario_id": a.usuario_id, "accion": a.accion, "objetivo": a.objetivo, "ip": a.ip, "exito": a.exito, "detalle": a.detalle, "creado_en": a.creado_en}
        for a in res.scalars().all()
    ]


@router.get("/resumen")
async def resumen(db: DB, _: Admin):
    """Números para el panel: familias, inscripciones, cupos, pendientes de moderación."""
    from app.models.participacion import EstadoModeracion, Testimonio
    from app.models.social import Comentario

    familias = await db.scalar(select(func.count()).select_from(Familia))
    activas = await db.scalar(select(func.count()).select_from(Actividad).where(Actividad.estado == EstadoActividad.activa))
    inscripciones = await db.scalar(select(func.count()).select_from(Inscripcion).where(Inscripcion.estado != EstadoInscripcion.cancelada))
    testimonios_pend = await db.scalar(select(func.count()).select_from(Testimonio).where(Testimonio.estado == EstadoModeracion.pendiente))
    comentarios_pend = await db.scalar(select(func.count()).select_from(Comentario).where(Comentario.estado == EstadoModeracion.pendiente))
    ciudades = (await db.execute(select(Ciudad.clave, Ciudad.nombre))).all()
    return {
        "familias": familias, "actividades_activas": activas, "inscripciones": inscripciones,
        "testimonios_pendientes": testimonios_pend, "comentarios_pendientes": comentarios_pend,
        "ciudades": [{"clave": c, "nombre": n} for c, n in ciudades],
    }

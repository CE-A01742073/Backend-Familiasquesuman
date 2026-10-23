"""Perfil (RF-18), familia e integrantes (RF-06, RF-11), insignias (RF-14), notificaciones,
y eliminación de cuenta (RF-15 — derecho de cancelación)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from sqlalchemy import delete, select, update
from sqlalchemy.orm import selectinload

from app.core import storage
from app.core.audit import auditar
from app.core.config import get_settings
from app.core.deps import DB, FamiliaActual, UsuarioActual
from app.core.metrics import UPLOADS_RECHAZADOS
from app.core.ratelimit import ip_cliente, limite_escritura, limite_general
from app.db.base import ahora
from app.models.catalogo import Actividad, Ciudad
from app.models.participacion import (
    Donacion,
    EstadoInscripcion,
    Inscripcion,
    Notificacion,
    Testimonio,
)
from app.models.social import Comentario, Conversacion, Like
from app.models.usuarios import Familia, Integrante, RefreshToken, Rol
from app.routers.auth import usuario_out
from app.schemas.auth import UsuarioOut
from app.schemas.comunes import Mensaje
from app.schemas.participacion import FamiliaOut, FamiliaPatch, IntegranteIn, IntegranteOut, NotificacionOut, PerfilPatch
from app.services import insignias

router = APIRouter(prefix="/me", tags=["me"], dependencies=[Depends(limite_general)])


@router.get("", response_model=UsuarioOut)
async def perfil(usuario: UsuarioActual):
    return usuario_out(usuario)


@router.patch("", response_model=UsuarioOut, dependencies=[Depends(limite_escritura)])
async def editar_perfil(datos: PerfilPatch, usuario: UsuarioActual, db: DB):
    if datos.nombre is not None:
        usuario.nombre = datos.nombre
    if datos.descripcion is not None:
        usuario.descripcion = datos.descripcion or None
    return usuario_out(usuario)


@router.put("/foto", response_model=UsuarioOut, dependencies=[Depends(limite_escritura)])
async def subir_foto(archivo: UploadFile, usuario: UsuarioActual, db: DB):
    """Foto de perfil (RF-18). Se valida por contenido, no por extensión, y se re-codifica sin metadatos."""
    datos = await _leer_imagen(archivo)
    key = storage.nueva_key("perfiles")
    await storage.guardar(key, datos)
    if usuario.foto_key:
        await storage.borrar(usuario.foto_key)
    usuario.foto_key = key
    return usuario_out(usuario)


async def _leer_imagen(archivo: UploadFile) -> bytes:
    s = get_settings()
    maximo = s.MAX_UPLOAD_MB * 1024 * 1024
    datos = await archivo.read(maximo + 1)
    if len(datos) > maximo:
        UPLOADS_RECHAZADOS.inc()
        raise HTTPException(413, f"La imagen no puede pesar más de {s.MAX_UPLOAD_MB} MB")
    try:
        return storage.normalizar_imagen(datos)
    except storage.ImagenInvalida as e:
        UPLOADS_RECHAZADOS.inc()
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(e))


# ---------- Familia ----------

@router.get("/familia", response_model=FamiliaOut)
async def mi_familia(familia: FamiliaActual):
    return familia


@router.patch("/familia", response_model=FamiliaOut, dependencies=[Depends(limite_escritura)])
async def editar_familia(datos: FamiliaPatch, familia: FamiliaActual, db: DB):
    if datos.nombre is not None:
        familia.nombre = datos.nombre
    if datos.zona is not None:
        familia.zona = datos.zona or None
    if datos.ciudad is not None:  # RF-02: la ciudad se puede cambiar en cualquier momento
        c = await db.scalar(select(Ciudad).where(Ciudad.clave == datos.ciudad.lower(), Ciudad.activa.is_(True)))
        if c is None:
            raise HTTPException(422, "Ciudad no disponible")
        familia.ciudad_id = c.id
    return familia


@router.post("/familia/integrantes", response_model=IntegranteOut, status_code=201, dependencies=[Depends(limite_escritura)])
async def agregar_integrante(datos: IntegranteIn, familia: FamiliaActual, db: DB):
    if len(familia.integrantes) >= 12:
        raise HTTPException(422, "Una familia puede tener máximo 12 integrantes")
    if any(i.nombre.lower() == datos.nombre.lower() for i in familia.integrantes):
        raise HTTPException(409, "Ya hay un integrante con ese nombre")
    i = Integrante(familia_id=familia.id, nombre=datos.nombre, edad=datos.edad)
    db.add(i)
    await db.flush()
    return i


@router.patch("/familia/integrantes/{integrante_id}", response_model=IntegranteOut, dependencies=[Depends(limite_escritura)])
async def editar_integrante(integrante_id: uuid.UUID, datos: IntegranteIn, familia: FamiliaActual, db: DB):
    i = next((x for x in familia.integrantes if x.id == integrante_id), None)  # solo los de MI familia
    if i is None:
        raise HTTPException(404, "Integrante no encontrado")
    if any(x.id != i.id and x.nombre.lower() == datos.nombre.lower() for x in familia.integrantes):
        raise HTTPException(409, "Ya hay un integrante con ese nombre")
    i.nombre, i.edad = datos.nombre, datos.edad
    return i


@router.delete("/familia/integrantes/{integrante_id}", response_model=Mensaje, dependencies=[Depends(limite_escritura)])
async def eliminar_integrante(integrante_id: uuid.UUID, familia: FamiliaActual, db: DB):
    i = next((x for x in familia.integrantes if x.id == integrante_id), None)
    if i is None:
        raise HTTPException(404, "Integrante no encontrado")
    if len(familia.integrantes) <= 1:
        raise HTTPException(422, "La familia debe tener al menos un integrante")
    await db.delete(i)
    return Mensaje(mensaje="Integrante eliminado")


# ---------- Insignias / historial ----------

@router.get("/insignias")
async def mis_insignias(familia: FamiliaActual, db: DB):
    return await insignias.resumen(db, familia.id)


# ---------- Notificaciones ----------

@router.get("/notificaciones", response_model=list[NotificacionOut])
async def notificaciones(usuario: UsuarioActual, db: DB, solo_no_leidas: bool = False):
    cond = [Notificacion.usuario_id == usuario.id]
    if solo_no_leidas:
        cond.append(Notificacion.leida.is_(False))
    res = await db.execute(select(Notificacion).where(*cond).order_by(Notificacion.creado_en.desc()).limit(100))
    return res.scalars().all()


@router.post("/notificaciones/leidas", response_model=Mensaje)
async def marcar_leidas(usuario: UsuarioActual, db: DB):
    await db.execute(update(Notificacion).where(Notificacion.usuario_id == usuario.id).values(leida=True))
    return Mensaje(mensaje="Notificaciones marcadas como leídas")


# ---------- Eliminación de cuenta (RF-15) ----------

@router.delete("", response_model=Mensaje, dependencies=[Depends(limite_escritura)])
async def eliminar_cuenta(usuario: UsuarioActual, request: Request, db: DB):
    """Borra o anonimiza TODO lo personal: integrantes, inscripciones (liberando cupos futuros),
    testimonios y sus fotos, comentarios, likes, conversaciones, notificaciones y sesiones.
    Se conserva solo una entrada de auditoría sin datos personales."""
    if usuario.rol == Rol.admin:
        raise HTTPException(422, "Una cuenta de administrador debe ser eliminada por otro administrador")

    uid = usuario.id
    fam = await db.scalar(select(Familia).options(selectinload(Familia.integrantes)).where(Familia.usuario_id == uid))
    if fam is not None:
        # Liberar cupos de actividades futuras
        res = await db.execute(
            select(Inscripcion).options(selectinload(Inscripcion.actividad))
            .where(Inscripcion.familia_id == fam.id, Inscripcion.estado == EstadoInscripcion.confirmada)
        )
        for ins in res.scalars().all():
            await db.execute(
                update(Actividad).where(Actividad.id == ins.actividad_id)
                .values(cupos_ocupados=Actividad.cupos_ocupados - ins.personas)
            )
        # Fotos en S3
        res = await db.execute(select(Testimonio.foto_key).where(Testimonio.familia_id == fam.id))
        for (key,) in res.all():
            if key:
                await storage.borrar(key)
        await db.execute(delete(Testimonio).where(Testimonio.familia_id == fam.id))
        await db.execute(delete(Inscripcion).where(Inscripcion.familia_id == fam.id))
        await db.execute(delete(Donacion).where(Donacion.familia_id == fam.id))
        await db.execute(delete(Conversacion).where(Conversacion.familia_id == fam.id))
        await db.delete(fam)  # integrantes en cascada

    await db.execute(delete(Comentario).where(Comentario.usuario_id == uid))
    await db.execute(delete(Like).where(Like.usuario_id == uid))
    await db.execute(delete(Notificacion).where(Notificacion.usuario_id == uid))
    await db.execute(delete(RefreshToken).where(RefreshToken.usuario_id == uid))
    if usuario.foto_key:
        await storage.borrar(usuario.foto_key)

    # Anonimizar el usuario (se conserva la fila para integridad referencial del audit log)
    usuario.email = f"eliminado-{uid}@invalido.local"
    usuario.nombre = "Usuario eliminado"
    usuario.descripcion = None
    usuario.foto_key = None
    usuario.password_hash = None
    usuario.google_sub = None
    usuario.activo = False
    usuario.eliminado_en = ahora()
    await auditar(db, "cuenta_eliminada", usuario_id=uid, ip=ip_cliente(request))
    return Mensaje(mensaje="Tu cuenta y tus datos fueron eliminados")

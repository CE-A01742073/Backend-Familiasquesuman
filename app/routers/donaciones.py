"""Donaciones en especie (RF-10): la familia registra qué va a llevar. No hay pagos."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select

from app.core.deps import DB, FamiliaActual
from app.core.idempotencia import clave_idempotencia, guardar_respuesta, reproducir, respuesta_previa, ruta_de
from app.core.ratelimit import limite_escritura, limite_general
from app.db.base import ahora
from app.models.catalogo import Campana, Centro
from app.models.participacion import Donacion
from app.schemas.participacion import DonacionIn, DonacionOut

router = APIRouter(prefix="/me/donaciones", tags=["donaciones"], dependencies=[Depends(limite_general)])


@router.get("", response_model=list[DonacionOut])
async def mis_donaciones(familia: FamiliaActual, db: DB):
    res = await db.execute(select(Donacion).where(Donacion.familia_id == familia.id).order_by(Donacion.creado_en.desc()))
    return res.scalars().all()


@router.post("", response_model=DonacionOut, status_code=201, dependencies=[Depends(limite_escritura)])
async def registrar(
    datos: DonacionIn,
    familia: FamiliaActual,
    request: Request,
    response: Response,
    db: DB,
    clave: str | None = Depends(clave_idempotencia),
):
    ruta = ruta_de(request)
    prev = await respuesta_previa(db, familia.usuario_id, clave, ruta)
    if prev:
        return reproducir(prev, response)

    centro_id: uuid.UUID | None = datos.centro_id
    if datos.campana_id is not None:
        c = await db.get(Campana, datos.campana_id)
        if c is None or not c.activa:
            raise HTTPException(404, "Campaña no encontrada")
        centro_id = c.centro_id
        ya = await db.scalar(select(Donacion.id).where(Donacion.familia_id == familia.id, Donacion.campana_id == c.id))
        if ya:
            raise HTTPException(409, "Ya registraste tu apoyo a esta campaña")
    if centro_id is None:
        raise HTTPException(422, "Indica una campaña o un centro")
    centro = await db.get(Centro, centro_id)
    if centro is None or not centro.activo:
        raise HTTPException(404, "Centro no encontrado")

    d = Donacion(
        familia_id=familia.id, centro_id=centro_id, campana_id=datos.campana_id,
        tipo=datos.tipo, detalle=datos.detalle, creado_en=ahora(),
    )
    db.add(d)
    await db.flush()
    salida = DonacionOut.model_validate(d)
    await guardar_respuesta(db, familia.usuario_id, clave, ruta, 201, salida.model_dump(mode="json"))
    return salida

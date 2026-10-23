"""Inscripciones (RF-05, RF-06, RF-11, RF-13). El cupo se actualiza de forma atómica en la BD:
dos familias peleando el último lugar → solo una gana, la otra recibe 409."""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.core.audit import auditar
from app.core.deps import DB, FamiliaActual
from app.core.idempotencia import clave_idempotencia, guardar_respuesta, reproducir, respuesta_previa, ruta_de
from app.core.metrics import INSCRIPCIONES
from app.core.ratelimit import ip_cliente, limite_escritura, limite_general
from app.db.base import ahora
from app.models.catalogo import Actividad, EstadoActividad
from app.models.participacion import Asistente, EncuestaRespuesta, EstadoInscripcion, Inscripcion, Momento
from app.schemas.participacion import ActividadResumen, EncuestaIn, EncuestaOut, InscripcionIn, InscripcionOut
from app.services.notificaciones import notificar

router = APIRouter(tags=["inscripciones"], dependencies=[Depends(limite_general)])

# RF-13: preguntas fijas. Las respuestas se validan contra estas claves.
ENCUESTAS = {
    "antes": [
        {"clave": "expectativa", "pregunta": "¿Qué esperan vivir en esta actividad?", "tipo": "texto"},
        {"clave": "animo", "pregunta": "¿Qué tan emocionada está la familia? (1–5)", "tipo": "escala"},
        {"clave": "primera_vez", "pregunta": "¿Es la primera vez que participan en voluntariado?", "tipo": "si_no"},
    ],
    "despues": [
        {"clave": "experiencia", "pregunta": "¿Cómo calificarían la experiencia? (1–5)", "tipo": "escala"},
        {"clave": "aprendizaje", "pregunta": "¿Qué aprendieron como familia?", "tipo": "texto"},
        {"clave": "repetiria", "pregunta": "¿Volverían a participar? (1–5)", "tipo": "escala"},
        {"clave": "recomendaria", "pregunta": "¿Recomendarían esta asociación?", "tipo": "si_no"},
    ],
}


def inscripcion_out(i: Inscripcion) -> InscripcionOut:
    o = InscripcionOut.model_validate(i)
    if i.actividad is not None:
        o.actividad = ActividadResumen.model_validate(i.actividad)
        o.actividad.centro_nombre = i.actividad.centro.nombre if i.actividad.centro else None
        o.actividad.estado = i.actividad.estado.value
    momentos = {e.momento for e in (i.encuestas or [])}
    o.encuesta_antes = Momento.antes in momentos
    o.encuesta_despues = Momento.despues in momentos
    return o


async def _cargar(db, inscripcion_id: uuid.UUID, familia_id: uuid.UUID) -> Inscripcion:
    i = await db.scalar(
        select(Inscripcion)
        .options(
            selectinload(Inscripcion.asistentes),
            selectinload(Inscripcion.encuestas),
            selectinload(Inscripcion.actividad).selectinload(Actividad.centro),
        )
        .where(Inscripcion.id == inscripcion_id, Inscripcion.familia_id == familia_id)  # A01: solo las mías
    )
    if i is None:
        raise HTTPException(404, "Inscripción no encontrada")
    return i


@router.get("/me/inscripciones", response_model=list[InscripcionOut])
async def mis_inscripciones(familia: FamiliaActual, db: DB, incluir_canceladas: bool = False):
    cond = [Inscripcion.familia_id == familia.id]
    if not incluir_canceladas:
        cond.append(Inscripcion.estado != EstadoInscripcion.cancelada)
    res = await db.execute(
        select(Inscripcion)
        .options(
            selectinload(Inscripcion.asistentes),
            selectinload(Inscripcion.encuestas),
            selectinload(Inscripcion.actividad).selectinload(Actividad.centro),
        )
        .where(*cond)
        .order_by(Inscripcion.creado_en.desc())
    )
    return [inscripcion_out(i) for i in res.scalars().all()]


@router.get("/me/inscripciones/{inscripcion_id}", response_model=InscripcionOut)
async def una_inscripcion(inscripcion_id: uuid.UUID, familia: FamiliaActual, db: DB):
    return inscripcion_out(await _cargar(db, inscripcion_id, familia.id))


@router.post(
    "/actividades/{actividad_id}/inscripciones",
    response_model=InscripcionOut,
    status_code=201,
    dependencies=[Depends(limite_escritura)],
)
async def inscribirse(
    actividad_id: uuid.UUID,
    datos: InscripcionIn,
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

    a = await db.scalar(select(Actividad).options(selectinload(Actividad.centro)).where(Actividad.id == actividad_id))
    if a is None:
        raise HTTPException(404, "Actividad no encontrada")
    if a.estado != EstadoActividad.activa or a.fecha < date.today():
        raise HTTPException(409, "Esta actividad ya no acepta inscripciones")

    # Integrantes: solo de MI familia y que cumplan la edad mínima (se valida en servidor, no solo en la app)
    mios = {i.id: i for i in familia.integrantes}
    elegidos = []
    for iid in datos.integrantes_ids:
        i = mios.get(iid)
        if i is None:
            raise HTTPException(422, "Hay integrantes que no pertenecen a tu familia")
        if i.edad < a.edad_minima:
            raise HTTPException(422, f"{i.nombre} no cumple la edad mínima ({a.edad_minima} años)")
        elegidos.append(i)

    ya = await db.scalar(
        select(Inscripcion.id).where(
            Inscripcion.actividad_id == a.id, Inscripcion.familia_id == familia.id,
            Inscripcion.estado != EstadoInscripcion.cancelada,
        )
    )
    if ya is not None:
        raise HTTPException(409, "Tu familia ya está inscrita en esta actividad")

    n = len(elegidos)
    # ---- Núcleo de RF-05: UPDATE condicional atómico. Nunca se sobrepasa el cupo. ----
    res = await db.execute(
        update(Actividad)
        .where(
            Actividad.id == a.id,
            Actividad.estado == EstadoActividad.activa,
            Actividad.cupos_ocupados + n <= Actividad.cupos_totales,
        )
        .values(cupos_ocupados=Actividad.cupos_ocupados + n)
        .returning(Actividad.cupos_ocupados)
    )
    if res.first() is None:
        INSCRIPCIONES.labels(resultado="sin_cupo").inc()
        disponibles = max(a.cupos_totales - a.cupos_ocupados, 0)
        raise HTTPException(
            409,
            f"Ya no hay cupo suficiente: quedan {disponibles} lugares y tu inscripción necesita {n}."
            if disponibles else "Ya no hay lugares disponibles para esta actividad",
        )

    ins = Inscripcion(actividad_id=a.id, familia_id=familia.id, comentario=datos.comentario or None, personas=n)
    ins.asistentes = [Asistente(integrante_id=i.id, nombre=i.nombre, edad=i.edad) for i in elegidos]
    db.add(ins)
    await db.flush()
    await db.refresh(a)
    INSCRIPCIONES.labels(resultado="ok").inc()
    notificar(
        db, familia.usuario_id, "Cupo confirmado",
        f"Tu familia está inscrita en '{a.titulo}' el {a.fecha.strftime('%d/%m/%Y')} a las {a.hora_inicio.strftime('%H:%M')}.",
        "inscripcion", ins.id,
    )
    await auditar(db, "inscripcion", usuario_id=familia.usuario_id, objetivo=str(a.id), ip=ip_cliente(request))

    salida = inscripcion_out(await _cargar(db, ins.id, familia.id))
    await guardar_respuesta(db, familia.usuario_id, clave, ruta, 201, salida.model_dump(mode="json"))
    return salida


@router.post("/me/inscripciones/{inscripcion_id}/cancelar", response_model=InscripcionOut, dependencies=[Depends(limite_escritura)])
async def cancelar(inscripcion_id: uuid.UUID, familia: FamiliaActual, request: Request, db: DB):
    i = await _cargar(db, inscripcion_id, familia.id)
    if i.estado != EstadoInscripcion.confirmada:
        raise HTTPException(409, "Esta inscripción ya no se puede cancelar")
    if i.actividad.fecha < date.today():
        raise HTTPException(409, "La actividad ya pasó")
    i.estado = EstadoInscripcion.cancelada
    await db.execute(
        update(Actividad).where(Actividad.id == i.actividad_id).values(cupos_ocupados=Actividad.cupos_ocupados - i.personas)
    )
    await auditar(db, "inscripcion_cancelada", usuario_id=familia.usuario_id, objetivo=str(i.id), ip=ip_cliente(request))
    await db.flush()
    return inscripcion_out(await _cargar(db, i.id, familia.id))


# ---------- Encuestas (RF-13) ----------

@router.get("/encuestas/{momento}")
async def preguntas(momento: Momento):
    return {"momento": momento, "preguntas": ENCUESTAS[momento.value]}


@router.post("/me/inscripciones/{inscripcion_id}/encuesta", response_model=EncuestaOut, status_code=201, dependencies=[Depends(limite_escritura)])
async def responder_encuesta(
    inscripcion_id: uuid.UUID,
    datos: EncuestaIn,
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

    i = await _cargar(db, inscripcion_id, familia.id)
    if i.estado == EstadoInscripcion.cancelada:
        raise HTTPException(409, "La inscripción está cancelada")
    if datos.momento == Momento.despues and i.actividad.fecha > date.today():
        raise HTTPException(409, "La encuesta 'después' se responde al terminar la actividad")
    if any(e.momento == datos.momento for e in i.encuestas):
        raise HTTPException(409, "Esta encuesta ya fue respondida")

    validas = {p["clave"]: p for p in ENCUESTAS[datos.momento.value]}
    limpias: dict[str, int | str] = {}
    for k, v in datos.respuestas.items():
        p = validas.get(k)
        if p is None:
            raise HTTPException(422, f"Pregunta desconocida: {k[:30]}")
        if p["tipo"] == "escala" and not (isinstance(v, int) and 1 <= v <= 5):
            raise HTTPException(422, f"'{k}' debe ser un número del 1 al 5")
        if p["tipo"] == "si_no" and v not in ("si", "no"):
            raise HTTPException(422, f"'{k}' debe ser 'si' o 'no'")
        if p["tipo"] == "texto":
            v = str(v)[:500]
        limpias[k] = v

    e = EncuestaRespuesta(inscripcion_id=i.id, momento=datos.momento, respuestas=limpias, creado_en=ahora())
    db.add(e)
    await db.flush()
    salida = EncuestaOut.model_validate(e)
    await guardar_respuesta(db, familia.usuario_id, clave, ruta, 201, salida.model_dump(mode="json"))
    return salida


@router.get("/me/inscripciones/{inscripcion_id}/encuestas", response_model=list[EncuestaOut])
async def mis_encuestas(inscripcion_id: uuid.UUID, familia: FamiliaActual, db: DB):
    i = await _cargar(db, inscripcion_id, familia.id)
    return i.encuestas

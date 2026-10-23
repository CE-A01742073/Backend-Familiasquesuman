"""Reconocimiento por participación (RF-14). Se calcula a partir de actividades con asistencia confirmada."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.participacion import EstadoInscripcion, Inscripcion

INSIGNIAS = [
    {"clave": "primer_paso", "nombre": "Primer paso", "descripcion": "Tu familia participó en su primera actividad", "minimo": 1},
    {"clave": "familia_solidaria", "nombre": "Familia solidaria", "descripcion": "3 actividades completadas", "minimo": 3},
    {"clave": "corazon_grande", "nombre": "Corazón grande", "descripcion": "5 actividades completadas", "minimo": 5},
    {"clave": "familia_que_suma", "nombre": "Familia que Suma", "descripcion": "10 actividades completadas", "minimo": 10},
    {"clave": "leyenda", "nombre": "Leyenda solidaria", "descripcion": "25 actividades completadas", "minimo": 25},
]

NIVELES = [(0, "Semilla"), (1, "Brote"), (3, "Planta"), (5, "Árbol"), (10, "Bosque")]


async def resumen(db: AsyncSession, familia_id: uuid.UUID) -> dict:
    total = await db.scalar(
        select(func.count())
        .select_from(Inscripcion)
        .where(Inscripcion.familia_id == familia_id, Inscripcion.estado == EstadoInscripcion.asistio)
    )
    total = int(total or 0)
    nivel = max((n for n in NIVELES if total >= n[0]), key=lambda n: n[0])
    siguiente = next((n for n in NIVELES if n[0] > total), None)
    return {
        "actividades_completadas": total,
        "nivel": nivel[1],
        "siguiente_nivel": siguiente[1] if siguiente else None,
        "faltan_para_siguiente": (siguiente[0] - total) if siguiente else 0,
        "insignias": [
            {**i, "obtenida": total >= i["minimo"]} for i in INSIGNIAS
        ],
    }

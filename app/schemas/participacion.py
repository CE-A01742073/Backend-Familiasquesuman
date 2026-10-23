import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, Field, field_validator

from app.models.participacion import EstadoInscripcion, EstadoModeracion, Momento
from app.schemas.comunes import Esquema


# ---- Familia e integrantes ----

class IntegranteIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=30)
    edad: int = Field(ge=0, le=120)


class IntegranteOut(Esquema):
    id: uuid.UUID
    nombre: str
    edad: int


class FamiliaOut(Esquema):
    id: uuid.UUID
    nombre: str
    zona: str | None
    ciudad_id: uuid.UUID | None
    integrantes: list[IntegranteOut]


class FamiliaPatch(BaseModel):
    nombre: str | None = Field(None, min_length=1, max_length=40)
    zona: str | None = Field(None, max_length=80)
    ciudad: str | None = Field(None, min_length=2, max_length=20)


class PerfilPatch(BaseModel):
    nombre: str | None = Field(None, min_length=2, max_length=80)
    descripcion: str | None = Field(None, max_length=300)


# ---- Inscripciones ----

class InscripcionIn(BaseModel):
    integrantes_ids: list[uuid.UUID] = Field(min_length=1, max_length=12)
    comentario: str | None = Field(None, max_length=300)

    @field_validator("integrantes_ids")
    @classmethod
    def _sin_duplicados(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(v)) != len(v):
            raise ValueError("Hay integrantes repetidos")
        return v


class AsistenteOut(Esquema):
    integrante_id: uuid.UUID | None
    nombre: str
    edad: int


class ActividadResumen(Esquema):
    id: uuid.UUID
    titulo: str
    fecha: date
    hora_inicio: time
    hora_fin: time | None
    lugar: str
    centro_id: uuid.UUID
    centro_nombre: str | None = None
    estado: str


class InscripcionOut(Esquema):
    id: uuid.UUID
    actividad_id: uuid.UUID
    familia_id: uuid.UUID
    comentario: str | None
    estado: EstadoInscripcion
    personas: int
    asistentes: list[AsistenteOut]
    actividad: ActividadResumen | None = None
    encuesta_antes: bool = False
    encuesta_despues: bool = False
    creado_en: datetime


class AsistenciaIn(BaseModel):
    """La asociación marca quién asistió."""
    asistieron: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    no_asistieron: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class AsistenteListaOut(Esquema):
    """Lista que recibe la asociación (RF-06)."""
    inscripcion_id: uuid.UUID
    familia_nombre: str
    contacto_email: str
    comentario: str | None
    estado: EstadoInscripcion
    personas: int
    asistentes: list[AsistenteOut]


# ---- Encuestas ----

class EncuestaIn(BaseModel):
    momento: Momento
    respuestas: dict[str, int | str] = Field(max_length=20)


class EncuestaOut(Esquema):
    inscripcion_id: uuid.UUID
    momento: Momento
    respuestas: dict
    creado_en: datetime


# ---- Donaciones ----

class DonacionIn(BaseModel):
    campana_id: uuid.UUID | None = None
    centro_id: uuid.UUID | None = None
    tipo: str = Field(min_length=2, max_length=40)
    detalle: str = Field(min_length=2, max_length=200)


class DonacionOut(Esquema):
    id: uuid.UUID
    centro_id: uuid.UUID
    campana_id: uuid.UUID | None
    tipo: str
    detalle: str
    creado_en: datetime


# ---- Testimonios ----

class TestimonioOut(Esquema):
    id: uuid.UUID
    familia_id: uuid.UUID
    familia_nombre: str | None = None
    actividad_id: uuid.UUID
    actividad_titulo: str | None = None
    texto: str
    foto_url: str | None = None
    estado: EstadoModeracion
    motivo_rechazo: str | None = None
    likes: int = 0
    me_gusta: bool = False
    creado_en: datetime


class ModeracionIn(BaseModel):
    aprobar: bool
    motivo: str | None = Field(None, max_length=200)


# ---- Notificaciones ----

class NotificacionOut(Esquema):
    id: uuid.UUID
    titulo: str
    cuerpo: str
    tipo: str
    referencia_id: uuid.UUID | None
    leida: bool
    creado_en: datetime

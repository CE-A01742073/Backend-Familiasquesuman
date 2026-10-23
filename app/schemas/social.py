import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.participacion import EstadoModeracion
from app.models.social import TipoObjetivo
from app.schemas.comunes import Esquema


class LikeOut(BaseModel):
    objetivo_tipo: TipoObjetivo
    objetivo_id: uuid.UUID
    likes: int
    me_gusta: bool


class ComentarioIn(BaseModel):
    texto: str = Field(min_length=1, max_length=400)


class ComentarioOut(Esquema):
    id: uuid.UUID
    objetivo_tipo: TipoObjetivo
    objetivo_id: uuid.UUID
    autor_nombre: str = ""
    es_mio: bool = False
    texto: str
    estado: EstadoModeracion
    creado_en: datetime


class ConversacionIn(BaseModel):
    centro_id: uuid.UUID
    texto: str = Field(min_length=1, max_length=1000)


class MensajeIn(BaseModel):
    texto: str = Field(min_length=1, max_length=1000)


class MensajeOut(Esquema):
    id: uuid.UUID
    conversacion_id: uuid.UUID
    emisor_rol: str
    es_mio: bool = False
    texto: str
    leido: bool
    creado_en: datetime


class ConversacionOut(Esquema):
    id: uuid.UUID
    familia_id: uuid.UUID
    familia_nombre: str | None = None
    centro_id: uuid.UUID
    centro_nombre: str | None = None
    bloqueada: bool
    no_leidos: int = 0
    ultimo_mensaje: MensajeOut | None = None
    actualizado_en: datetime


class ReporteIn(BaseModel):
    objetivo_tipo: str = Field(pattern=r"^(comentario|mensaje|testimonio)$")
    objetivo_id: uuid.UUID
    motivo: str = Field(min_length=3, max_length=300)


class RolIn(BaseModel):
    rol: str = Field(pattern=r"^(familia|asociacion|admin)$")
    centro_id: uuid.UUID | None = None


class UsuarioAdminOut(Esquema):
    id: uuid.UUID
    email: str
    nombre: str
    rol: str
    activo: bool
    centro_id: uuid.UUID | None
    bloqueado_hasta: datetime | None
    creado_en: datetime

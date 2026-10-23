import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, Field, field_validator

from app.models.catalogo import Categoria, CategoriaDonacion, EstadoActividad
from app.schemas.comunes import Esquema


class CiudadOut(Esquema):
    id: uuid.UUID
    clave: str
    nombre: str
    estado: str


class CentroOut(Esquema):
    id: uuid.UUID
    nombre: str
    tipo: str
    categoria: Categoria
    descripcion: str
    direccion: str
    horario_visitas: str | None
    que_necesitan: list[str]
    acepta: list[str]
    telefono: str | None
    whatsapp: str | None
    correo: str | None
    verificado: bool
    activo: bool
    ciudad_id: uuid.UUID
    imagen_url: str | None = None
    actualizado_en: datetime


class CentroIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    tipo: str = Field(min_length=2, max_length=60)
    categoria: Categoria
    descripcion: str = Field(min_length=10, max_length=2000)
    direccion: str = Field(min_length=5, max_length=200)
    horario_visitas: str | None = Field(None, max_length=120)
    que_necesitan: list[str] = Field(default_factory=list, max_length=20)
    acepta: list[CategoriaDonacion] = Field(default_factory=list)
    telefono: str | None = Field(None, pattern=r"^\d{10}$")
    whatsapp: str | None = Field(None, pattern=r"^\d{10}$")
    correo: str | None = Field(None, max_length=254)
    ciudad: str = Field(min_length=2, max_length=20)

    @field_validator("que_necesitan")
    @classmethod
    def _items(cls, v: list[str]) -> list[str]:
        return [x.strip()[:80] for x in v if x.strip()]


class CentroPatch(BaseModel):
    nombre: str | None = Field(None, min_length=2, max_length=120)
    tipo: str | None = Field(None, min_length=2, max_length=60)
    categoria: Categoria | None = None
    descripcion: str | None = Field(None, min_length=10, max_length=2000)
    direccion: str | None = Field(None, min_length=5, max_length=200)
    horario_visitas: str | None = Field(None, max_length=120)
    que_necesitan: list[str] | None = Field(None, max_length=20)
    acepta: list[CategoriaDonacion] | None = None
    telefono: str | None = Field(None, pattern=r"^\d{10}$")
    whatsapp: str | None = Field(None, pattern=r"^\d{10}$")
    correo: str | None = Field(None, max_length=254)
    activo: bool | None = None


class ActividadOut(Esquema):
    id: uuid.UUID
    centro_id: uuid.UUID
    centro_nombre: str | None = None
    ciudad_id: uuid.UUID
    titulo: str
    categoria: Categoria
    fecha: date
    hora_inicio: time
    hora_fin: time | None
    lugar: str
    descripcion: str
    requisitos: list[str]
    edad_minima: int
    apta_ninos: bool
    cupos_totales: int
    cupos_ocupados: int
    cupos_disponibles: int = 0
    estado: EstadoActividad
    imagen_url: str | None = None
    likes: int = 0
    me_gusta: bool = False
    actualizado_en: datetime


class ActividadIn(BaseModel):
    titulo: str = Field(min_length=3, max_length=120)
    categoria: Categoria
    fecha: date
    hora_inicio: time
    hora_fin: time | None = None
    lugar: str = Field(min_length=3, max_length=200)
    descripcion: str = Field(min_length=10, max_length=2000)
    requisitos: list[str] = Field(default_factory=list, max_length=15)
    edad_minima: int = Field(0, ge=0, le=120)
    apta_ninos: bool = True
    cupos_totales: int = Field(ge=1, le=500)


class ActividadPatch(BaseModel):
    titulo: str | None = Field(None, min_length=3, max_length=120)
    categoria: Categoria | None = None
    fecha: date | None = None
    hora_inicio: time | None = None
    hora_fin: time | None = None
    lugar: str | None = Field(None, min_length=3, max_length=200)
    descripcion: str | None = Field(None, min_length=10, max_length=2000)
    requisitos: list[str] | None = Field(None, max_length=15)
    edad_minima: int | None = Field(None, ge=0, le=120)
    apta_ninos: bool | None = None
    cupos_totales: int | None = Field(None, ge=1, le=500)
    estado: EstadoActividad | None = None


class CampanaOut(Esquema):
    id: uuid.UUID
    centro_id: uuid.UUID
    centro_nombre: str | None = None
    ciudad_id: uuid.UUID
    titulo: str
    descripcion: str
    que_llevar: list[str]
    donde_entregar: str | None
    horario_entrega: str | None
    hasta: date | None
    activa: bool
    imagen_url: str | None = None
    likes: int = 0
    me_gusta: bool = False
    ya_apoye: bool = False
    actualizado_en: datetime


class CampanaIn(BaseModel):
    titulo: str = Field(min_length=3, max_length=120)
    descripcion: str = Field(min_length=10, max_length=2000)
    que_llevar: list[str] = Field(default_factory=list, max_length=20)
    donde_entregar: str | None = Field(None, max_length=200)
    horario_entrega: str | None = Field(None, max_length=120)
    hasta: date | None = None


class CampanaPatch(BaseModel):
    titulo: str | None = Field(None, min_length=3, max_length=120)
    descripcion: str | None = Field(None, min_length=10, max_length=2000)
    que_llevar: list[str] | None = Field(None, max_length=20)
    donde_entregar: str | None = Field(None, max_length=200)
    horario_entrega: str | None = Field(None, max_length=120)
    hasta: date | None = None
    activa: bool | None = None


class ProyectoOut(Esquema):
    id: uuid.UUID
    centro_id: uuid.UUID
    centro_nombre: str | None = None
    titulo: str
    causa: str
    objetivo: str
    descripcion: str
    avance: float
    activo: bool
    imagen_url: str | None = None
    likes: int = 0
    me_gusta: bool = False
    creado_en: datetime
    actualizado_en: datetime


class ProyectoIn(BaseModel):
    titulo: str = Field(min_length=3, max_length=120)
    causa: str = Field(min_length=2, max_length=60)
    objetivo: str = Field(min_length=2, max_length=120)
    descripcion: str = Field(min_length=10, max_length=2000)
    avance: float = Field(0, ge=0, le=1)


class ProyectoPatch(BaseModel):
    titulo: str | None = Field(None, min_length=3, max_length=120)
    causa: str | None = Field(None, min_length=2, max_length=60)
    objetivo: str | None = Field(None, min_length=2, max_length=120)
    descripcion: str | None = Field(None, min_length=10, max_length=2000)
    avance: float | None = Field(None, ge=0, le=1)
    activo: bool | None = None


class AvisoOut(Esquema):
    version: str
    contenido: str
    publicado_en: datetime

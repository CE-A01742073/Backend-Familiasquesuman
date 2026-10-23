import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Esquema(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)


class Pagina(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class Paginacion(BaseModel):
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)


class Mensaje(BaseModel):
    mensaje: str


class ConId(Esquema):
    id: uuid.UUID


class ConTiempos(Esquema):
    creado_en: datetime
    actualizado_en: datetime

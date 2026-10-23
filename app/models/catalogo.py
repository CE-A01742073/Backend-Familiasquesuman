import enum
import uuid
from datetime import date, datetime, time

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum, Float, ForeignKey, Integer, String, Text, Time
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ConId, ConTiempos


class Categoria(str, enum.Enum):
    ninos = "ninos"
    adultos_mayores = "adultos_mayores"
    medio_ambiente = "medio_ambiente"
    animales = "animales"
    comunidad = "comunidad"


class CategoriaDonacion(str, enum.Enum):
    juguetes = "juguetes"
    ropa = "ropa"
    alimentos = "alimentos"
    higiene = "higiene"
    sillas_ruedas = "sillas_ruedas"
    utiles = "utiles"
    cobijas = "cobijas"
    croquetas = "croquetas"


class EstadoActividad(str, enum.Enum):
    activa = "activa"
    cancelada = "cancelada"
    finalizada = "finalizada"


class Ciudad(ConId, Base):
    __tablename__ = "ciudades"

    clave: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # monterrey, hermosillo
    nombre: Mapped[str] = mapped_column(String(60), nullable=False)
    estado: Mapped[str] = mapped_column(String(60), nullable=False)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Centro(ConId, ConTiempos, Base):
    __tablename__ = "centros"

    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    tipo: Mapped[str] = mapped_column(String(60), nullable=False)
    categoria: Mapped[Categoria] = mapped_column(Enum(Categoria, name="categoria"), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    direccion: Mapped[str] = mapped_column(String(200), nullable=False)
    horario_visitas: Mapped[str | None] = mapped_column(String(120))
    que_necesitan: Mapped[list[str]] = mapped_column(ARRAY(String(80)), nullable=False, default=list)
    acepta: Mapped[list[str]] = mapped_column(ARRAY(String(30)), nullable=False, default=list)
    telefono: Mapped[str | None] = mapped_column(String(20))
    whatsapp: Mapped[str | None] = mapped_column(String(20))
    correo: Mapped[str | None] = mapped_column(String(254))
    verificado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ciudad_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ciudades.id"), nullable=False, index=True)
    imagen_key: Mapped[str | None] = mapped_column(String(255))

    ciudad: Mapped[Ciudad] = relationship()


class Actividad(ConId, ConTiempos, Base):
    __tablename__ = "actividades"
    __table_args__ = (
        CheckConstraint("cupos_ocupados >= 0 AND cupos_ocupados <= cupos_totales", name="ck_cupos"),
        CheckConstraint("edad_minima >= 0 AND edad_minima <= 120", name="ck_edad_minima"),
    )

    centro_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("centros.id"), nullable=False, index=True)
    ciudad_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ciudades.id"), nullable=False, index=True)
    titulo: Mapped[str] = mapped_column(String(120), nullable=False)
    categoria: Mapped[Categoria] = mapped_column(Enum(Categoria, name="categoria", create_type=False), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hora_inicio: Mapped[time] = mapped_column(Time, nullable=False)
    hora_fin: Mapped[time | None] = mapped_column(Time)
    lugar: Mapped[str] = mapped_column(String(200), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    requisitos: Mapped[list[str]] = mapped_column(ARRAY(String(80)), nullable=False, default=list)
    edad_minima: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    apta_ninos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cupos_totales: Mapped[int] = mapped_column(Integer, nullable=False)
    cupos_ocupados: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # personas, no familias
    estado: Mapped[EstadoActividad] = mapped_column(
        Enum(EstadoActividad, name="estado_actividad"), nullable=False, default=EstadoActividad.activa
    )
    imagen_key: Mapped[str | None] = mapped_column(String(255))

    centro: Mapped[Centro] = relationship()


class Campana(ConId, ConTiempos, Base):
    __tablename__ = "campanas"

    centro_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("centros.id"), nullable=False, index=True)
    ciudad_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ciudades.id"), nullable=False, index=True)
    titulo: Mapped[str] = mapped_column(String(120), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    que_llevar: Mapped[list[str]] = mapped_column(ARRAY(String(80)), nullable=False, default=list)
    donde_entregar: Mapped[str | None] = mapped_column(String(200))
    horario_entrega: Mapped[str | None] = mapped_column(String(120))
    hasta: Mapped[date | None] = mapped_column(Date)
    activa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    imagen_key: Mapped[str | None] = mapped_column(String(255))

    centro: Mapped[Centro] = relationship()


class Proyecto(ConId, ConTiempos, Base):
    __tablename__ = "proyectos"
    __table_args__ = (CheckConstraint("avance >= 0 AND avance <= 1", name="ck_avance"),)

    centro_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("centros.id"), nullable=False, index=True)
    titulo: Mapped[str] = mapped_column(String(120), nullable=False)
    causa: Mapped[str] = mapped_column(String(60), nullable=False)
    objetivo: Mapped[str] = mapped_column(String(120), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    avance: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    imagen_key: Mapped[str | None] = mapped_column(String(255))

    centro: Mapped[Centro] = relationship()


class AvisoPrivacidad(ConId, Base):
    """Versión vigente del aviso: la app muestra siempre la última (RF-15)."""

    __tablename__ = "avisos_privacidad"

    version: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    contenido: Mapped[str] = mapped_column(Text, nullable=False)  # markdown
    publicado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

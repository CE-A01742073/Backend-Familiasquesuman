import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ConId, ConTiempos


class EstadoInscripcion(str, enum.Enum):
    confirmada = "confirmada"
    cancelada = "cancelada"
    asistio = "asistio"
    no_asistio = "no_asistio"


class EstadoModeracion(str, enum.Enum):
    pendiente = "pendiente"
    aprobado = "aprobado"
    rechazado = "rechazado"


class Momento(str, enum.Enum):
    antes = "antes"
    despues = "despues"


class Inscripcion(ConId, ConTiempos, Base):
    __tablename__ = "inscripciones"
    __table_args__ = (
        # Una familia solo puede tener UNA inscripción no cancelada por actividad (RF-05).
        Index(
            "uq_inscripcion_activa",
            "actividad_id",
            "familia_id",
            unique=True,
            postgresql_where="estado <> 'cancelada'",
        ),
    )

    actividad_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("actividades.id"), nullable=False, index=True
    )
    familia_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("familias.id", ondelete="CASCADE"), nullable=False, index=True
    )
    comentario: Mapped[str | None] = mapped_column(String(300))
    estado: Mapped[EstadoInscripcion] = mapped_column(
        Enum(EstadoInscripcion, name="estado_inscripcion"), nullable=False, default=EstadoInscripcion.confirmada
    )
    personas: Mapped[int] = mapped_column(Integer, nullable=False)  # cupos que ocupa

    actividad: Mapped["Actividad"] = relationship()  # noqa: F821
    familia: Mapped["Familia"] = relationship()  # noqa: F821
    asistentes: Mapped[list["Asistente"]] = relationship(back_populates="inscripcion", cascade="all, delete-orphan")
    encuestas: Mapped[list["EncuestaRespuesta"]] = relationship(cascade="all, delete-orphan")


class Asistente(ConId, Base):
    """Snapshot de quién va: si la familia edita un integrante después, la lista enviada no cambia."""

    __tablename__ = "asistentes"

    inscripcion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inscripciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integrante_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    nombre: Mapped[str] = mapped_column(String(30), nullable=False)
    edad: Mapped[int] = mapped_column(Integer, nullable=False)

    inscripcion: Mapped[Inscripcion] = relationship(back_populates="asistentes")


class EncuestaRespuesta(ConId, Base):
    __tablename__ = "encuesta_respuestas"
    __table_args__ = (UniqueConstraint("inscripcion_id", "momento", name="uq_encuesta_momento"),)

    inscripcion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inscripciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    momento: Mapped[Momento] = mapped_column(Enum(Momento, name="momento"), nullable=False)
    respuestas: Mapped[dict] = mapped_column(JSONB, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Donacion(ConId, Base):
    """Compromiso de donación en especie. La app no procesa pagos (RF-10)."""

    __tablename__ = "donaciones"
    __table_args__ = (UniqueConstraint("familia_id", "campana_id", name="uq_donacion_campana"),)

    familia_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("familias.id", ondelete="CASCADE"), nullable=False, index=True
    )
    centro_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("centros.id"), nullable=False)
    campana_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campanas.id"))
    tipo: Mapped[str] = mapped_column(String(40), nullable=False)
    detalle: Mapped[str] = mapped_column(String(200), nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Testimonio(ConId, ConTiempos, Base):
    __tablename__ = "testimonios"

    familia_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("familias.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actividad_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("actividades.id"), nullable=False)
    texto: Mapped[str] = mapped_column(String(600), nullable=False)
    foto_key: Mapped[str | None] = mapped_column(String(255))
    estado: Mapped[EstadoModeracion] = mapped_column(
        Enum(EstadoModeracion, name="estado_moderacion"), nullable=False, default=EstadoModeracion.pendiente, index=True
    )
    motivo_rechazo: Mapped[str | None] = mapped_column(String(200))
    moderado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    moderado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    familia: Mapped["Familia"] = relationship()  # noqa: F821
    actividad: Mapped["Actividad"] = relationship()  # noqa: F821


class Notificacion(ConId, Base):
    __tablename__ = "notificaciones"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    titulo: Mapped[str] = mapped_column(String(80), nullable=False)
    cuerpo: Mapped[str] = mapped_column(String(300), nullable=False)
    tipo: Mapped[str] = mapped_column(String(30), nullable=False)
    referencia_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    leida: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClaveIdempotencia(Base):
    """Respuestas guardadas para reintentos del sync offline: mismo (usuario, clave) → misma respuesta."""

    __tablename__ = "claves_idempotencia"

    usuario_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    clave: Mapped[str] = mapped_column(String(64), primary_key=True)
    ruta: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    cuerpo: Mapped[dict] = mapped_column(JSONB, nullable=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

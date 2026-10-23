import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ConId, ConTiempos
from app.models.participacion import EstadoModeracion


class TipoObjetivo(str, enum.Enum):
    actividad = "actividad"
    campana = "campana"
    proyecto = "proyecto"
    testimonio = "testimonio"


class Like(Base):
    __tablename__ = "likes"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True
    )
    objetivo_tipo: Mapped[TipoObjetivo] = mapped_column(Enum(TipoObjetivo, name="tipo_objetivo"), primary_key=True)
    objetivo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Comentario(ConId, ConTiempos, Base):
    __tablename__ = "comentarios"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    objetivo_tipo: Mapped[TipoObjetivo] = mapped_column(
        Enum(TipoObjetivo, name="tipo_objetivo", create_type=False), nullable=False
    )
    objetivo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    texto: Mapped[str] = mapped_column(String(400), nullable=False)
    estado: Mapped[EstadoModeracion] = mapped_column(
        Enum(EstadoModeracion, name="estado_moderacion", create_type=False),
        nullable=False,
        default=EstadoModeracion.pendiente,
        index=True,
    )
    moderado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))

    usuario: Mapped["Usuario"] = relationship()  # noqa: F821


class Conversacion(ConId, ConTiempos, Base):
    """Solo familia ↔ asociación (centro). Nunca familia ↔ familia (protección de menores)."""

    __tablename__ = "conversaciones"
    __table_args__ = (UniqueConstraint("familia_id", "centro_id", name="uq_conversacion"),)

    familia_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("familias.id", ondelete="CASCADE"), nullable=False, index=True
    )
    centro_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("centros.id"), nullable=False, index=True)
    bloqueada: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    mensajes: Mapped[list["Mensaje"]] = relationship(back_populates="conversacion", cascade="all, delete-orphan")


class Mensaje(ConId, Base):
    __tablename__ = "mensajes"

    conversacion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversaciones.id", ondelete="CASCADE"), nullable=False, index=True
    )
    emisor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="SET NULL"))
    emisor_rol: Mapped[str] = mapped_column(String(20), nullable=False)  # familia | asociacion
    texto: Mapped[str] = mapped_column(String(1000), nullable=False)
    leido: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    conversacion: Mapped[Conversacion] = relationship(back_populates="mensajes")


class Reporte(ConId, Base):
    __tablename__ = "reportes"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="SET NULL"), index=True
    )
    objetivo_tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # comentario | mensaje | testimonio
    objetivo_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    motivo: Mapped[str] = mapped_column(String(300), nullable=False)
    atendido: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

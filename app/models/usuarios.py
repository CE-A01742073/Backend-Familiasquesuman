import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ConId, ConTiempos


class Rol(str, enum.Enum):
    familia = "familia"
    asociacion = "asociacion"
    admin = "admin"


class Usuario(ConId, ConTiempos, Base):
    __tablename__ = "usuarios"

    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))  # argon2id; null si solo Google
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    rol: Mapped[Rol] = mapped_column(Enum(Rol, name="rol"), nullable=False, default=Rol.familia)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(300))
    foto_key: Mapped[str | None] = mapped_column(String(255))
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    eliminado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Control de fuerza bruta por cuenta (A07)
    intentos_fallidos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Asociación: centro que administra
    centro_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("centros.id", ondelete="SET NULL"))

    familia: Mapped["Familia | None"] = relationship(back_populates="usuario", uselist=False, cascade="all, delete-orphan")
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="usuario", cascade="all, delete-orphan")


class Familia(ConId, ConTiempos, Base):
    __tablename__ = "familias"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    nombre: Mapped[str] = mapped_column(String(40), nullable=False)
    zona: Mapped[str | None] = mapped_column(String(80))
    ciudad_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ciudades.id", ondelete="SET NULL"))

    usuario: Mapped[Usuario] = relationship(back_populates="familia")
    integrantes: Mapped[list["Integrante"]] = relationship(
        back_populates="familia", cascade="all, delete-orphan", order_by="Integrante.creado_en"
    )


class Integrante(ConId, ConTiempos, Base):
    __tablename__ = "integrantes"
    __table_args__ = (UniqueConstraint("familia_id", "nombre", name="uq_integrante_nombre_familia"),)

    familia_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("familias.id", ondelete="CASCADE"), nullable=False, index=True
    )
    nombre: Mapped[str] = mapped_column(String(30), nullable=False)
    edad: Mapped[int] = mapped_column(Integer, nullable=False)

    familia: Mapped[Familia] = relationship(back_populates="integrantes")


class RefreshToken(ConId, Base):
    __tablename__ = "refresh_tokens"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # sha256 hex
    expira_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revocado: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reemplazado_por: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(200))

    usuario: Mapped[Usuario] = relationship(back_populates="refresh_tokens")


class AuditLog(ConId, Base):
    """Bitácora de acciones sensibles (A09). Nunca guarda contraseñas ni tokens."""

    __tablename__ = "audit_log"

    usuario_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    accion: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    objetivo: Mapped[str | None] = mapped_column(String(120))
    ip: Mapped[str | None] = mapped_column(String(64))
    exito: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    detalle: Mapped[str | None] = mapped_column(Text)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

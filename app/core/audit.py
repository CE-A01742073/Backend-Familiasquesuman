import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import ahora
from app.models.usuarios import AuditLog


async def auditar(
    db: AsyncSession,
    accion: str,
    *,
    usuario_id: uuid.UUID | None = None,
    objetivo: str | None = None,
    ip: str | None = None,
    exito: bool = True,
    detalle: str | None = None,
) -> None:
    """Registra la acción. Nunca pasar contraseñas, tokens ni datos de menores en `detalle`."""
    db.add(
        AuditLog(
            usuario_id=usuario_id,
            accion=accion,
            objetivo=objetivo[:120] if objetivo else None,
            ip=ip[:64] if ip else None,
            exito=exito,
            detalle=detalle[:500] if detalle else None,
            creado_en=ahora(),
        )
    )

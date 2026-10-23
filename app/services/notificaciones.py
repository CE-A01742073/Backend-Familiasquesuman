import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import ahora
from app.models.participacion import Notificacion


def notificar(
    db: AsyncSession, usuario_id: uuid.UUID, titulo: str, cuerpo: str, tipo: str, referencia_id: uuid.UUID | None = None
) -> Notificacion:
    n = Notificacion(
        usuario_id=usuario_id, titulo=titulo[:80], cuerpo=cuerpo[:300], tipo=tipo, referencia_id=referencia_id, creado_en=ahora()
    )
    db.add(n)
    return n

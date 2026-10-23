import uuid
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.social import Like, TipoObjetivo


def url_imagen(key: str | None) -> str | None:
    if not key:
        return None
    return f"{get_settings().API_PREFIX}/archivos/{key}"


async def likes_de(
    db: AsyncSession, tipo: TipoObjetivo, ids: Iterable[uuid.UUID], usuario_id: uuid.UUID | None
) -> dict[uuid.UUID, tuple[int, bool]]:
    ids = list(ids)
    if not ids:
        return {}
    res = await db.execute(
        select(Like.objetivo_id, func.count())
        .where(Like.objetivo_tipo == tipo, Like.objetivo_id.in_(ids))
        .group_by(Like.objetivo_id)
    )
    conteo = {oid: int(c) for oid, c in res.all()}
    mios: set[uuid.UUID] = set()
    if usuario_id is not None:
        res2 = await db.execute(
            select(Like.objetivo_id).where(
                Like.objetivo_tipo == tipo, Like.objetivo_id.in_(ids), Like.usuario_id == usuario_id
            )
        )
        mios = {r[0] for r in res2.all()}
    return {i: (conteo.get(i, 0), i in mios) for i in ids}

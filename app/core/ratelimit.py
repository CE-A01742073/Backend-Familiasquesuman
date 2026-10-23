"""Rate limiting de ventana fija por IP (A07: fuerza bruta). Redis si está configurado; si no, memoria."""
import asyncio
import time

from fastapi import HTTPException, Request, status

from app.core.config import get_settings


class _MemoriaStore:
    def __init__(self) -> None:
        self._datos: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def incr(self, clave: str, ventana: int) -> int:
        async with self._lock:
            ahora = time.monotonic()
            cuenta, expira = self._datos.get(clave, (0, ahora + ventana))
            if expira <= ahora:
                cuenta, expira = 0, ahora + ventana
            cuenta += 1
            self._datos[clave] = (cuenta, expira)
            if len(self._datos) > 50_000:  # limpieza simple
                self._datos = {k: v for k, v in self._datos.items() if v[1] > ahora}
            return cuenta

    async def reset(self) -> None:
        async with self._lock:
            self._datos.clear()


class _RedisStore:
    def __init__(self, url: str) -> None:
        import redis.asyncio as redis  # import perezoso: dependencia opcional

        self._r = redis.from_url(url)

    async def incr(self, clave: str, ventana: int) -> int:
        pipe = self._r.pipeline()
        pipe.incr(clave)
        pipe.expire(clave, ventana, nx=True)
        cuenta, _ = await pipe.execute()
        return int(cuenta)

    async def reset(self) -> None:
        await self._r.flushdb()


_store = None


def store():
    global _store
    if _store is None:
        s = get_settings()
        _store = _RedisStore(s.REDIS_URL) if s.REDIS_URL else _MemoriaStore()
    return _store


def ip_cliente(request: Request) -> str:
    s = get_settings()
    if s.TRUST_PROXY_HEADERS:
        # Cloudflare pone la IP real aquí; el túnel no permite que el cliente la falsifique.
        cf = request.headers.get("cf-connecting-ip")
        if cf:
            return cf
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return request.client.host if request.client else "desconocido"


def limitar(nombre: str, por_minuto_attr: str):
    """Dependencia de FastAPI: `Depends(limitar("auth", "RATE_LIMIT_AUTH_PER_MINUTE"))`."""

    async def _dep(request: Request) -> None:
        s = get_settings()
        ip = ip_cliente(request)
        if ip in s.rate_limit_exempt_ips:
            return
        limite = getattr(s, por_minuto_attr)
        clave = f"rl:{nombre}:{ip}:{int(time.time() // 60)}"
        cuenta = await store().incr(clave, 60)
        if cuenta > limite:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demasiadas solicitudes. Intenta de nuevo en un minuto.",
                headers={"Retry-After": "60"},
            )

    return _dep


limite_auth = limitar("auth", "RATE_LIMIT_AUTH_PER_MINUTE")
limite_general = limitar("general", "RATE_LIMIT_GENERAL_PER_MINUTE")
limite_escritura = limitar("escritura", "RATE_LIMIT_WRITE_PER_MINUTE")

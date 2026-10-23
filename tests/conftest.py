"""Pruebas contra un PostgreSQL real (TEST_DATABASE_URL). El almacenamiento S3 se simula en memoria."""
import io
import os
import uuid
from datetime import date, time, timedelta

os.environ["ENV"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5432/familias_test?host=/tmp"
)
os.environ["JWT_SECRET"] = "secreto-de-pruebas-0123456789abcdefghijklmnopqrstuvwxyz"
os.environ["METRICS_TOKEN"] = "token-metricas-prueba"
os.environ["RATE_LIMIT_AUTH_PER_MINUTE"] = "10"
os.environ["LOGIN_MAX_FAILS"] = "5"
os.environ["GOOGLE_CLIENT_IDS"] = "cliente-prueba.apps.googleusercontent.com"

import httpx  # noqa: E402
import pytest  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core import ratelimit, storage  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Actividad, Categoria, Centro, Ciudad, Familia, Integrante, Rol, Usuario  # noqa: E402
from app.models.catalogo import AvisoPrivacidad  # noqa: E402
from app.db.base import ahora  # noqa: E402

PASSWORD = "ContrasenaSegura2026!"


@pytest.fixture(scope="session", autouse=True)
async def _esquema():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _limpiar():
    """Tablas vacías y rate limiter en cero antes de cada prueba."""
    yield
    async with engine.begin() as conn:
        tablas = ", ".join(t.name for t in Base.metadata.sorted_tables)
        await conn.execute(text(f"TRUNCATE {tablas} CASCADE"))
    await ratelimit.store().reset()


@pytest.fixture(autouse=True)
def _s3_en_memoria(monkeypatch):
    bucket: dict[str, bytes] = {}

    async def guardar(key, datos):
        bucket[key] = datos

    async def leer(key):
        return bucket.get(key)

    async def borrar(key):
        bucket.pop(key, None)

    monkeypatch.setattr(storage, "guardar", guardar)
    monkeypatch.setattr(storage, "leer", leer)
    monkeypatch.setattr(storage, "borrar", borrar)
    return bucket


@pytest.fixture
async def cliente():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as c:
        yield c


@pytest.fixture
async def db():
    async with SessionLocal() as s:
        yield s
        await s.commit()


# ---------- datos base ----------

@pytest.fixture
async def ciudad(db) -> Ciudad:
    c = Ciudad(clave="monterrey", nombre="Monterrey", estado="Nuevo León")
    db.add(c)
    db.add(Ciudad(clave="hermosillo", nombre="Hermosillo", estado="Sonora"))
    db.add(AvisoPrivacidad(version="1.0", contenido="# Aviso de prueba", publicado_en=ahora()))
    await db.commit()
    return c


@pytest.fixture
async def centro(db, ciudad) -> Centro:
    c = Centro(
        nombre="Regalando Estrellas", tipo="Asociación civil", categoria=Categoria.ninos,
        descripcion="Visitas al hospital con regalos para familias.", direccion="Av. San Rafael 450, Guadalupe",
        horario_visitas="Sábados", que_necesitan=["Juguetes"], acepta=["juguetes"], telefono="8181234507",
        verificado=True, ciudad_id=ciudad.id,
    )
    db.add(c)
    await db.commit()
    return c


@pytest.fixture
async def otro_centro(db, ciudad) -> Centro:
    c = Centro(
        nombre="Cíclica", tipo="Asociación civil", categoria=Categoria.medio_ambiente,
        descripcion="Reciclaje y talleres ambientales para familias.", direccion="Col. Contry, Monterrey",
        que_necesitan=[], acepta=[], verificado=True, ciudad_id=ciudad.id,
    )
    db.add(c)
    await db.commit()
    return c


def _actividad(centro: Centro, **kw) -> Actividad:
    base = dict(
        centro_id=centro.id, ciudad_id=centro.ciudad_id, titulo="Visita al Materno Infantil", categoria=Categoria.ninos,
        fecha=date.today() + timedelta(days=7), hora_inicio=time(9, 45), hora_fin=time(12, 0),
        lugar="Hospital Materno Infantil", descripcion="Entrega de desayunos y regalos a las familias del hospital.",
        requisitos=["Llegar 15 minutos antes"], edad_minima=6, apta_ninos=True, cupos_totales=10, cupos_ocupados=0,
    )
    base.update(kw)
    return Actividad(**base)


@pytest.fixture
async def actividad(db, centro) -> Actividad:
    a = _actividad(centro)
    db.add(a)
    await db.commit()
    return a


async def crear_usuario(db, email: str, rol: Rol = Rol.familia, ciudad: Ciudad | None = None, centro_id=None,
                        integrantes=(("Ana", 41), ("Carlos", 43), ("Sofía", 12), ("Mateo", 4))) -> Usuario:
    u = Usuario(email=email, password_hash=hash_password(PASSWORD), nombre=email.split("@")[0].title(), rol=rol, centro_id=centro_id)
    db.add(u)
    await db.flush()
    if rol == Rol.familia:
        f = Familia(usuario_id=u.id, nombre=f"Familia {u.nombre}", ciudad_id=ciudad.id if ciudad else None)
        f.integrantes = [Integrante(nombre=n, edad=e) for n, e in integrantes]
        db.add(f)
    await db.commit()
    return u


async def login(cliente, email: str, password: str = PASSWORD) -> dict:
    r = await cliente.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture
async def familia_a(db, ciudad, cliente):
    await crear_usuario(db, "ana@familia-a.com", ciudad=ciudad)
    t = await login(cliente, "ana@familia-a.com")
    return auth(t)


@pytest.fixture
async def familia_b(db, ciudad, cliente):
    await crear_usuario(db, "beto@familia-b.com", ciudad=ciudad)
    t = await login(cliente, "beto@familia-b.com")
    return auth(t)


@pytest.fixture
async def asociacion(db, ciudad, centro, cliente):
    await crear_usuario(db, "asociacion@centro.com", rol=Rol.asociacion, centro_id=centro.id)
    return auth(await login(cliente, "asociacion@centro.com"))


@pytest.fixture
async def admin(db, ciudad, cliente):
    await crear_usuario(db, "admin@fqs.com", rol=Rol.admin)
    return auth(await login(cliente, "admin@fqs.com"))


def imagen_png(ancho: int = 64, ruido: bool = False) -> bytes:
    buf = io.BytesIO()
    if ruido:  # incompresible → pesa ~3 bytes por píxel
        img = Image.frombytes("RGB", (ancho, ancho), os.urandom(ancho * ancho * 3))
    else:
        img = Image.new("RGB", (ancho, ancho), (31, 58, 95))
    img.save(buf, format="PNG")
    return buf.getvalue()


async def integrantes_de(cliente, headers) -> list[dict]:
    r = await cliente.get("/api/v1/me/familia", headers=headers)
    assert r.status_code == 200
    return r.json()["integrantes"]


def uid() -> str:
    return str(uuid.uuid4())

"""Autenticación: RF-16, RF-17 y controles A07 (fuerza bruta, JWT, refresh)."""
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings
from tests.conftest import PASSWORD, auth, crear_usuario, login

REGISTRO = {
    "email": "nueva@familia.com", "password": PASSWORD, "nombre": "Laura Pérez",
    "nombre_familia": "Familia Pérez", "ciudad": "monterrey", "acepta_aviso_privacidad": True,
}


async def test_registro_crea_cuenta_y_familia(cliente, ciudad):
    r = await cliente.post("/api/v1/auth/registro", json=REGISTRO)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["familia_creada"] is True and d["usuario"]["rol"] == "familia"
    fam = await cliente.get("/api/v1/me/familia", headers=auth(d))
    assert fam.status_code == 200 and fam.json()["nombre"] == "Familia Pérez"


async def test_registro_exige_aviso_y_password_fuerte(cliente, ciudad):
    r = await cliente.post("/api/v1/auth/registro", json={**REGISTRO, "acepta_aviso_privacidad": False})
    assert r.status_code == 422
    r = await cliente.post("/api/v1/auth/registro", json={**REGISTRO, "password": "corta1"})
    assert r.status_code == 422 and "12 caracteres" in r.text
    r = await cliente.post("/api/v1/auth/registro", json={**REGISTRO, "password": "123456789012"})
    assert r.status_code == 422


async def test_registro_duplicado(cliente, ciudad):
    assert (await cliente.post("/api/v1/auth/registro", json=REGISTRO)).status_code == 201
    r = await cliente.post("/api/v1/auth/registro", json=REGISTRO)
    assert r.status_code == 409


async def test_login_ok_y_mensaje_generico_en_error(cliente, db, ciudad):
    await crear_usuario(db, "ana@x.com", ciudad=ciudad)
    ok = await login(cliente, "ana@x.com")
    assert ok["token_type"] == "bearer" and ok["expires_in"] == 15 * 60
    mal = await cliente.post("/api/v1/auth/login", json={"email": "ana@x.com", "password": "incorrecta-123"})
    inexistente = await cliente.post("/api/v1/auth/login", json={"email": "nadie@x.com", "password": "incorrecta-123"})
    assert mal.status_code == inexistente.status_code == 401
    assert mal.json()["error"]["mensaje"] == inexistente.json()["error"]["mensaje"]  # no revela si existe


async def test_bloqueo_por_fuerza_bruta(cliente, db, ciudad):
    """A07: tras 5 fallos la cuenta se bloquea aunque después se mande la contraseña correcta."""
    await crear_usuario(db, "victima@x.com", ciudad=ciudad)
    for _ in range(5):
        r = await cliente.post("/api/v1/auth/login", json={"email": "victima@x.com", "password": "adivinando-123"})
        assert r.status_code == 401
    r = await cliente.post("/api/v1/auth/login", json={"email": "victima@x.com", "password": PASSWORD})
    assert r.status_code == 423, r.text


async def test_rate_limit_por_ip(cliente, db, ciudad):
    """A07: más de 10 peticiones/min a /auth desde la misma IP → 429."""
    codigos = []
    for _ in range(11):
        r = await cliente.post("/api/v1/auth/login", json={"email": "x@x.com", "password": "loquesea-1234"})
        codigos.append(r.status_code)
    assert codigos[-1] == 429 and codigos[0] == 401


async def test_jwt_manipulado_y_alg_none(cliente, db, ciudad):
    u = await crear_usuario(db, "ana@x.com", ciudad=ciudad)
    t = await login(cliente, "ana@x.com")
    s = get_settings()
    # 1) firma con otro secreto
    falso = jwt.encode({"sub": str(u.id), "rol": "admin", "type": "access", "jti": "x", "iat": datetime.now(timezone.utc),
                        "exp": datetime.now(timezone.utc) + timedelta(minutes=5), "iss": s.JWT_ISSUER, "aud": s.JWT_AUDIENCE},
                       "otro-secreto-muy-largo-0123456789abcdef", algorithm="HS256")
    assert (await cliente.get("/api/v1/me", headers={"Authorization": f"Bearer {falso}"})).status_code == 401
    # 2) alg=none
    none = jwt.encode({"sub": str(u.id), "rol": "admin"}, None, algorithm="none")
    assert (await cliente.get("/api/v1/me", headers={"Authorization": f"Bearer {none}"})).status_code == 401
    # 3) expirado
    exp = jwt.encode({"sub": str(u.id), "rol": "familia", "type": "access", "jti": "x", "iat": datetime.now(timezone.utc) - timedelta(hours=1),
                      "exp": datetime.now(timezone.utc) - timedelta(minutes=30), "iss": s.JWT_ISSUER, "aud": s.JWT_AUDIENCE},
                     s.JWT_SECRET, algorithm="HS256")
    assert (await cliente.get("/api/v1/me", headers={"Authorization": f"Bearer {exp}"})).status_code == 401
    # 4) rol en el token NO otorga privilegios: se re-lee de la BD
    escalado = jwt.encode({"sub": str(u.id), "rol": "admin", "type": "access", "jti": "x", "iat": datetime.now(timezone.utc),
                           "exp": datetime.now(timezone.utc) + timedelta(minutes=5), "iss": s.JWT_ISSUER, "aud": s.JWT_AUDIENCE},
                          s.JWT_SECRET, algorithm="HS256")
    assert (await cliente.get("/api/v1/gestion/usuarios", headers={"Authorization": f"Bearer {escalado}"})).status_code == 403
    # 5) token válido sí funciona
    assert (await cliente.get("/api/v1/me", headers=auth(t))).status_code == 200


async def test_refresh_rota_y_detecta_reuso(cliente, db, ciudad):
    await crear_usuario(db, "ana@x.com", ciudad=ciudad)
    t1 = await login(cliente, "ana@x.com")
    r = await cliente.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})
    assert r.status_code == 200
    t2 = r.json()
    assert t2["refresh_token"] != t1["refresh_token"]
    # reuso del token viejo → robo detectado → TODA la familia de tokens queda revocada
    assert (await cliente.post("/api/v1/auth/refresh", json={"refresh_token": t1["refresh_token"]})).status_code == 401
    assert (await cliente.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})).status_code == 401


async def test_logout_revoca_refresh(cliente, db, ciudad):
    await crear_usuario(db, "ana@x.com", ciudad=ciudad)
    t = await login(cliente, "ana@x.com")
    assert (await cliente.post("/api/v1/auth/logout", json={"refresh_token": t["refresh_token"]}, headers=auth(t))).status_code == 200
    assert (await cliente.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]})).status_code == 401


async def test_cambiar_password(cliente, db, ciudad):
    await crear_usuario(db, "ana@x.com", ciudad=ciudad)
    t = await login(cliente, "ana@x.com")
    r = await cliente.post("/api/v1/auth/cambiar-password", headers=auth(t),
                           json={"password_actual": "equivocada-12345", "password_nueva": "NuevaClaveLarga2026"})
    assert r.status_code == 401
    r = await cliente.post("/api/v1/auth/cambiar-password", headers=auth(t),
                           json={"password_actual": PASSWORD, "password_nueva": "NuevaClaveLarga2026"})
    assert r.status_code == 200
    assert (await cliente.post("/api/v1/auth/login", json={"email": "ana@x.com", "password": PASSWORD})).status_code == 401
    assert (await cliente.post("/api/v1/auth/login", json={"email": "ana@x.com", "password": "NuevaClaveLarga2026"})).status_code == 200


async def test_google_crea_cuenta_y_vincula(cliente, db, ciudad, monkeypatch):
    from app.routers import auth as auth_router

    async def _fake(token):
        if token == "token-google-valido-de-maria-xxxxxxxx":
            return {"sub": "g-123", "email": "maria@gmail.com", "email_verified": True, "name": "María"}
        from fastapi import HTTPException
        raise HTTPException(401, "Token de Google inválido")

    monkeypatch.setattr(auth_router, "_verificar_google", _fake)
    # token inválido
    r = await cliente.post("/api/v1/auth/google", json={"id_token": "token-invalido-xxxxxxxxxxxxxxxxxx"})
    assert r.status_code == 401
    # primera vez sin datos de familia
    r = await cliente.post("/api/v1/auth/google", json={"id_token": "token-google-valido-de-maria-xxxxxxxx"})
    assert r.status_code == 422
    r = await cliente.post("/api/v1/auth/google", json={"id_token": "token-google-valido-de-maria-xxxxxxxx",
                                                        "nombre_familia": "Familia Gómez", "ciudad": "monterrey", "acepta_aviso_privacidad": True})
    assert r.status_code == 200 and r.json()["familia_creada"] is True
    # segunda vez: misma cuenta, sin crear familia
    r = await cliente.post("/api/v1/auth/google", json={"id_token": "token-google-valido-de-maria-xxxxxxxx"})
    assert r.status_code == 200 and r.json()["familia_creada"] is False and r.json()["usuario"]["tiene_google"]


async def test_aviso_privacidad_es_publico(cliente, ciudad):
    r = await cliente.get("/api/v1/aviso-privacidad")
    assert r.status_code == 200 and r.json()["version"] == "1.0"

"""A02 / A05 / A10: cabeceras, errores sin fuga de información, inyección, tamaño de cuerpo, /metrics."""
import pytest



async def test_cabeceras_de_seguridad(cliente, ciudad):
    r = await cliente.get("/api/v1/aviso-privacidad")
    h = r.headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert "default-src 'none'" in h["content-security-policy"]
    assert h["referrer-policy"] == "no-referrer"
    assert h["cache-control"] == "no-store"
    assert "x-request-id" in h


async def test_errores_no_filtran_detalles(cliente, familia_a, monkeypatch):
    # 404 genérico en JSON
    r = await cliente.get("/api/v1/no-existe", headers=familia_a)
    assert r.status_code == 404 and r.json()["error"]["codigo"] == "http_error"
    # 405
    r = await cliente.delete("/api/v1/ciudades", headers=familia_a)
    assert r.status_code == 405
    # excepción interna → 500 sin traceback ni mensaje de la excepción
    from app.routers import catalogo

    async def explota(*a, **k):
        raise RuntimeError("conexion a 10.0.0.5 fallo: password=abc")

    monkeypatch.setattr(catalogo, "ciudad_de_usuario", explota)
    r = await cliente.get("/api/v1/actividades", headers=familia_a)
    assert r.status_code == 500
    cuerpo = r.text
    assert "10.0.0.5" not in cuerpo and "password" not in cuerpo and "Traceback" not in cuerpo
    assert r.json()["error"]["mensaje"] == "Ocurrió un error inesperado"


async def test_json_malformado_y_validacion_sin_eco(cliente, ciudad):
    r = await cliente.post("/api/v1/auth/login", content=b'{"email": "a@b.c", "password": ', headers={"Content-Type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["detalles"][0]["error"] == "JSON inválido"
    payload = "<script>alert(1)</script>"
    r = await cliente.post("/api/v1/auth/login", json={"email": payload, "password": "x" * 12})
    assert r.status_code == 422 and payload not in r.text  # no se refleja la entrada


async def test_inyeccion_sql_en_parametros(cliente, familia_a, actividad, centro):
    """Las cadenas maliciosas se tratan como datos, sin error 500 ni fuga."""
    for mal in ["' OR 1=1--", "\"; DROP TABLE usuarios; --", "%' UNION SELECT email, password_hash FROM usuarios--", "1; SELECT pg_sleep(5)"]:
        r = await cliente.get("/api/v1/actividades", headers=familia_a, params={"q": mal})
        assert r.status_code == 200 and r.json()["total"] == 0, mal
        r = await cliente.get("/api/v1/centros", headers=familia_a, params={"q": mal})
        assert r.status_code == 200 and r.json()["total"] == 0, mal
        r = await cliente.post("/api/v1/auth/login", json={"email": "ana@familia-a.com", "password": mal})
        assert r.status_code == 401
    assert (await cliente.get("/api/v1/actividades/not-a-uuid", headers=familia_a)).status_code == 422
    assert (await cliente.get("/api/v1/actividades?limit=99999", headers=familia_a)).status_code == 422
    assert (await cliente.get("/api/v1/proyectos?orden=DROP", headers=familia_a)).status_code == 422
    assert (await cliente.get("/api/v1/me", headers=familia_a)).status_code == 200
    async def test_bytes_nul_rechazados_sin_500(cliente, familia_a):
    r = await cliente.get("/api/v1/campanas?ciudad=%27%22%00%3Cscript%3E&limit=50", headers=familia_a)
    assert r.status_code == 400 and r.json()["error"]["codigo"] == "entrada_invalida"
    r = await cliente.patch("/api/v1/me/familia", json={"nombre": "Familia\u0000X"}, headers=familia_a)
    assert r.status_code == 400
    r = await cliente.patch("/api/v1/me/familia", json={"nombre": "Familia Garza"}, headers=familia_a)
    assert r.status_code == 200


async def test_cuerpo_demasiado_grande(cliente, familia_a):
    r = await cliente.post("/api/v1/me/familia/integrantes", headers={**familia_a, "Content-Length": str(50 * 1024 * 1024)}, content=b"{}")
    assert r.status_code == 413


async def test_metrics_protegido(cliente):
    assert (await cliente.get("/metrics")).status_code == 401
    assert (await cliente.get("/metrics", headers={"Authorization": "Bearer incorrecto"})).status_code == 401
    r = await cliente.get("/metrics", headers={"Authorization": "Bearer token-metricas-prueba"})
    assert r.status_code == 200 and b"familias_logins_fallidos_total" in r.content


async def test_docs_apagados_en_prod():
    """En prod no existe /docs ni /openapi.json (ver main.py); aquí se verifica la regla de configuración."""
    from app.core.config import Settings
    s = Settings(ENV="prod", JWT_SECRET="4f1c9e7b2a6d8c0e5b3a7f9d1c2e4b6a8d0f3c5e7a9b1d2f4e6c8a0b2d4f6e8a")
    assert s.es_prod
    with pytest.raises(ValueError):
        Settings(ENV="prod", JWT_SECRET="changeme-changeme-changeme-changeme-changeme")


async def test_health(cliente):
    r = await cliente.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"

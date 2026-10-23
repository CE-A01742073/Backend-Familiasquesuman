"""A01 Broken Access Control: cada usuario solo ve y modifica lo suyo; los roles se verifican en servidor."""
from datetime import date, timedelta

from tests.conftest import _actividad, auth, crear_usuario, integrantes_de, login


async def _inscribir(cliente, headers, actividad_id, n=1):
    ints = await integrantes_de(cliente, headers)
    r = await cliente.post(f"/api/v1/actividades/{actividad_id}/inscripciones", headers=headers,
                           json={"integrantes_ids": [i["id"] for i in ints[:n]]})
    assert r.status_code == 201, r.text
    return r.json()


async def test_familia_no_ve_inscripcion_de_otra(cliente, familia_a, familia_b, actividad):
    ins = await _inscribir(cliente, familia_a, actividad.id)
    # B intenta leer, cancelar y responder encuesta de la inscripción de A (IDOR)
    assert (await cliente.get(f"/api/v1/me/inscripciones/{ins['id']}", headers=familia_b)).status_code == 404
    assert (await cliente.post(f"/api/v1/me/inscripciones/{ins['id']}/cancelar", headers=familia_b)).status_code == 404
    r = await cliente.post(f"/api/v1/me/inscripciones/{ins['id']}/encuesta", headers=familia_b,
                           json={"momento": "antes", "respuestas": {"animo": 5}})
    assert r.status_code == 404
    # A sí puede
    assert (await cliente.get(f"/api/v1/me/inscripciones/{ins['id']}", headers=familia_a)).status_code == 200


async def test_integrantes_de_otra_familia_no_se_pueden_usar(cliente, familia_a, familia_b, actividad):
    ints_b = await integrantes_de(cliente, familia_b)
    r = await cliente.post(f"/api/v1/actividades/{actividad.id}/inscripciones", headers=familia_a,
                           json={"integrantes_ids": [ints_b[0]["id"]]})
    assert r.status_code == 422
    # ni editarlos / borrarlos
    assert (await cliente.patch(f"/api/v1/me/familia/integrantes/{ints_b[0]['id']}", headers=familia_a,
                                json={"nombre": "Hackeado", "edad": 30})).status_code == 404
    assert (await cliente.delete(f"/api/v1/me/familia/integrantes/{ints_b[0]['id']}", headers=familia_a)).status_code == 404


async def test_familia_no_accede_a_gestion_ni_admin(cliente, familia_a, actividad, centro):
    assert (await cliente.get("/api/v1/gestion/usuarios", headers=familia_a)).status_code == 403
    assert (await cliente.get("/api/v1/gestion/centros", headers=familia_a)).status_code == 403
    assert (await cliente.get(f"/api/v1/gestion/actividades/{actividad.id}/asistentes", headers=familia_a)).status_code == 403
    assert (await cliente.post(f"/api/v1/gestion/centros/{centro.id}/actividades", headers=familia_a, json={})).status_code == 403
    assert (await cliente.get("/api/v1/admin/testimonios", headers=familia_a)).status_code == 403
    assert (await cliente.get("/api/v1/gestion/auditoria", headers=familia_a)).status_code == 403


async def test_asociacion_solo_su_centro(cliente, db, asociacion, admin, centro, otro_centro, actividad):
    """La asociación de 'Regalando Estrellas' no puede tocar actividades de 'Cíclica'."""
    ajena = _actividad(otro_centro, titulo="Taller de reciclaje")
    db.add(ajena)
    await db.commit()
    # propia: sí
    assert (await cliente.patch(f"/api/v1/gestion/actividades/{actividad.id}", headers=asociacion, json={"cupos_totales": 12})).status_code == 200
    assert (await cliente.get(f"/api/v1/gestion/actividades/{actividad.id}/asistentes", headers=asociacion)).status_code == 200
    # ajena: 404 (no se confirma que exista)
    assert (await cliente.patch(f"/api/v1/gestion/actividades/{ajena.id}", headers=asociacion, json={"cupos_totales": 1})).status_code == 404
    assert (await cliente.get(f"/api/v1/gestion/actividades/{ajena.id}/asistentes", headers=asociacion)).status_code == 404
    assert (await cliente.post(f"/api/v1/gestion/centros/{otro_centro.id}/actividades", headers=asociacion, json={
        "titulo": "Intrusa", "categoria": "ninos", "fecha": str(date.today() + timedelta(days=3)), "hora_inicio": "10:00",
        "lugar": "Col. Contry", "descripcion": "descripcion larga suficiente", "cupos_totales": 5})).status_code == 404
    # tampoco es admin
    assert (await cliente.get("/api/v1/gestion/usuarios", headers=asociacion)).status_code == 403
    assert (await cliente.post(f"/api/v1/gestion/centros/{otro_centro.id}/verificar", headers=asociacion)).status_code == 403
    assert (await cliente.get("/api/v1/admin/testimonios", headers=asociacion)).status_code == 403
    # admin sí puede con cualquiera
    assert (await cliente.patch(f"/api/v1/gestion/actividades/{ajena.id}", headers=admin, json={"cupos_totales": 20})).status_code == 200


async def test_admin_no_puede_cambiar_su_propio_rol(cliente, admin):
    me = (await cliente.get("/api/v1/me", headers=admin)).json()
    r = await cliente.patch(f"/api/v1/gestion/usuarios/{me['id']}/rol", headers=admin, json={"rol": "familia"})
    assert r.status_code == 422


async def test_admin_asigna_rol_asociacion(cliente, db, admin, ciudad, centro):
    u = await crear_usuario(db, "nueva@asoc.com", ciudad=ciudad)
    r = await cliente.patch(f"/api/v1/gestion/usuarios/{u.id}/rol", headers=admin, json={"rol": "asociacion"})
    assert r.status_code == 422  # falta centro
    r = await cliente.patch(f"/api/v1/gestion/usuarios/{u.id}/rol", headers=admin, json={"rol": "asociacion", "centro_id": str(centro.id)})
    assert r.status_code == 200 and r.json()["rol"] == "asociacion"
    t = await login(cliente, "nueva@asoc.com")
    assert (await cliente.get("/api/v1/gestion/centros", headers=auth(t))).json()[0]["id"] == str(centro.id)


async def test_usuario_desactivado_pierde_acceso(cliente, db, admin, ciudad):
    u = await crear_usuario(db, "ana@x.com", ciudad=ciudad)
    t = await login(cliente, "ana@x.com")
    assert (await cliente.get("/api/v1/me", headers=auth(t))).status_code == 200
    assert (await cliente.post(f"/api/v1/gestion/usuarios/{u.id}/desactivar", headers=admin)).status_code == 200
    # el access token aún vigente deja de servir de inmediato (se re-lee la BD)
    assert (await cliente.get("/api/v1/me", headers=auth(t))).status_code == 401
    assert (await cliente.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]})).status_code == 401


async def test_archivos_sin_traversal_ni_fuga(cliente, familia_a):
    for key in ["../../etc/passwd", "perfiles/../../x.jpg", "perfiles/%2e%2e/x.jpg", "otros/" + "a" * 32 + ".jpg", "perfiles/" + "z" * 32 + ".jpg"]:
        r = await cliente.get(f"/api/v1/archivos/{key}", headers=familia_a)
        assert r.status_code == 404, key


async def test_sin_token_todo_es_401(cliente, ciudad):
    for ruta in ["/api/v1/me", "/api/v1/centros", "/api/v1/actividades", "/api/v1/me/inscripciones", "/api/v1/gestion/usuarios",
                 f"/api/v1/archivos/perfiles/{'a' * 32}.jpg", "/api/v1/conversaciones", "/api/v1/sync"]:
        r = await cliente.get(ruta)
        assert r.status_code == 401, ruta
        assert r.headers.get("www-authenticate") == "Bearer"


async def test_asociacion_lista_y_edita_campanas_y_proyectos_de_su_centro(cliente, asociacion, centro, otro_centro):
    """Las listas de gestión incluyen lo inactivo (para reactivarlo) y solo del centro propio."""
    r = await cliente.post(f"/api/v1/gestion/centros/{centro.id}/campanas", headers=asociacion, json={
        "titulo": "Cobijas de invierno", "descripcion": "Cobijas nuevas o en buen estado para familias."})
    assert r.status_code == 201, r.text
    campana_id = r.json()["id"]
    assert (await cliente.patch(f"/api/v1/gestion/campanas/{campana_id}", headers=asociacion, json={"activa": False})).status_code == 200

    r = await cliente.get(f"/api/v1/gestion/centros/{centro.id}/campanas", headers=asociacion)
    assert r.status_code == 200 and [c["id"] for c in r.json()] == [campana_id] and r.json()[0]["activa"] is False
    assert (await cliente.get(f"/api/v1/gestion/centros/{otro_centro.id}/campanas", headers=asociacion)).status_code == 404

    r = await cliente.post(f"/api/v1/gestion/centros/{centro.id}/proyectos", headers=asociacion, json={
        "titulo": "Biblioteca móvil", "causa": "Educación", "objetivo": "500 libros", "descripcion": "Libros para colonias sin biblioteca."})
    assert r.status_code == 201, r.text
    r = await cliente.get(f"/api/v1/gestion/centros/{centro.id}/proyectos", headers=asociacion)
    assert r.status_code == 200 and len(r.json()) == 1
    assert (await cliente.get(f"/api/v1/gestion/centros/{otro_centro.id}/proyectos", headers=asociacion)).status_code == 404

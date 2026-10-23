"""RF-12 (testimonios moderados), RF-15 (eliminación de cuenta), RF-18 (perfil), A08 (uploads), comentarios, mensajes."""
from datetime import date, timedelta

from sqlalchemy import select

from app.models import Actividad, Familia, Integrante, Usuario
from tests.conftest import imagen_png, integrantes_de


async def _participar(cliente, db, headers, actividad):
    ints = await integrantes_de(cliente, headers)
    ins = (await cliente.post(f"/api/v1/actividades/{actividad.id}/inscripciones", headers=headers,
                              json={"integrantes_ids": [ints[0]["id"]]})).json()
    act = await db.get(Actividad, actividad.id)
    act.fecha = date.today() - timedelta(days=2)
    await db.commit()
    return ins


async def test_testimonio_solo_tras_participar_y_requiere_moderacion(cliente, db, familia_a, familia_b, admin, actividad, _s3_en_memoria):
    # sin haber participado → 409
    r = await cliente.post("/api/v1/me/testimonios", headers=familia_a, data={"actividad_id": str(actividad.id), "texto": "Fue una experiencia increíble"})
    assert r.status_code == 409
    await _participar(cliente, db, familia_a, actividad)
    # archivo que NO es imagen (php renombrado) → 415
    r = await cliente.post("/api/v1/me/testimonios", headers=familia_a, data={"actividad_id": str(actividad.id), "texto": "Fue una experiencia increíble"},
                           files={"foto": ("foto.jpg", b"<?php system($_GET['c']); ?>", "image/jpeg")})
    assert r.status_code == 415
    # imagen real → pendiente
    r = await cliente.post("/api/v1/me/testimonios", headers=familia_a, data={"actividad_id": str(actividad.id), "texto": "Fue una experiencia increíble"},
                           files={"foto": ("foto.png", imagen_png(), "image/png")})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["estado"] == "pendiente" and t["foto_url"]
    # se guardó re-codificada como JPEG (sin metadatos)
    assert list(_s3_en_memoria.values())[0][:3] == b"\xff\xd8\xff"
    # nadie más lo ve: ni en la lista pública ni la foto
    assert (await cliente.get("/api/v1/testimonios", headers=familia_b)).json()["total"] == 0
    assert (await cliente.get(t["foto_url"], headers=familia_b)).status_code == 404
    assert (await cliente.get(t["foto_url"], headers=familia_a)).status_code == 200  # la dueña sí
    # duplicado → 409
    r = await cliente.post("/api/v1/me/testimonios", headers=familia_a, data={"actividad_id": str(actividad.id), "texto": "Otro testimonio repetido"})
    assert r.status_code == 409
    # admin lo ve pendiente y lo aprueba
    pend = (await cliente.get("/api/v1/admin/testimonios", headers=admin)).json()
    assert pend["total"] == 1
    r = await cliente.post(f"/api/v1/admin/testimonios/{t['id']}/moderar", headers=admin, json={"aprobar": True})
    assert r.status_code == 200 and r.json()["estado"] == "aprobado"
    # ahora sí es público
    pub = (await cliente.get("/api/v1/testimonios", headers=familia_b)).json()
    assert pub["total"] == 1 and pub["items"][0]["familia_nombre"].startswith("Familia")
    assert (await cliente.get(t["foto_url"], headers=familia_b)).status_code == 200
    # la familia recibió notificación
    assert any(n["tipo"] == "testimonio" for n in (await cliente.get("/api/v1/me/notificaciones", headers=familia_a)).json())


async def test_testimonio_rechazado_con_motivo(cliente, db, familia_a, familia_b, admin, actividad):
    await _participar(cliente, db, familia_a, actividad)
    t = (await cliente.post("/api/v1/me/testimonios", headers=familia_a, data={"actividad_id": str(actividad.id), "texto": "Texto suficientemente largo"})).json()
    r = await cliente.post(f"/api/v1/admin/testimonios/{t['id']}/moderar", headers=admin, json={"aprobar": False, "motivo": "Aparecen rostros de menores"})
    assert r.json()["estado"] == "rechazado" and r.json()["motivo_rechazo"] == "Aparecen rostros de menores"
    assert (await cliente.get("/api/v1/testimonios", headers=familia_b)).json()["total"] == 0
    assert (await cliente.get("/api/v1/me/testimonios", headers=familia_a)).json()[0]["estado"] == "rechazado"


async def test_foto_perfil_y_tamano_maximo(cliente, familia_a, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "MAX_UPLOAD_MB", 1)
    grande = imagen_png(800, ruido=True)  # ~1.9 MB, > 1 MB
    r = await cliente.put("/api/v1/me/foto", headers=familia_a, files={"archivo": ("f.png", grande, "image/png")})
    assert r.status_code == 413
    r = await cliente.put("/api/v1/me/foto", headers=familia_a, files={"archivo": ("f.png", imagen_png(), "image/png")})
    assert r.status_code == 200 and r.json()["tiene_foto"] is True
    r = await cliente.patch("/api/v1/me", headers=familia_a, json={"nombre": "Ana R.", "descripcion": "Nos encanta ayudar"})
    assert r.json()["nombre"] == "Ana R." and r.json()["descripcion"] == "Nos encanta ayudar"


async def test_eliminar_cuenta_borra_todo(cliente, db, familia_a, actividad, _s3_en_memoria):
    """RF-15: lo que dice el aviso de privacidad se cumple de verdad."""
    ins = await _participar(cliente, db, familia_a, actividad)
    act = await db.get(Actividad, actividad.id)
    act.fecha = date.today() + timedelta(days=3)  # vuelve a ser futura para probar liberación de cupo
    await db.commit()
    await cliente.put("/api/v1/me/foto", headers=familia_a, files={"archivo": ("f.png", imagen_png(), "image/png")})
    me = (await cliente.get("/api/v1/me", headers=familia_a)).json()
    assert (await cliente.get(f"/api/v1/actividades/{actividad.id}", headers=familia_a)).json()["cupos_ocupados"] == 1
    assert len(_s3_en_memoria) == 1

    r = await cliente.delete("/api/v1/me", headers=familia_a)
    assert r.status_code == 200
    # token inválido, login imposible, datos borrados
    assert (await cliente.get("/api/v1/me", headers=familia_a)).status_code == 401
    assert (await cliente.post("/api/v1/auth/login", json={"email": "ana@familia-a.com", "password": "ContrasenaSegura2026!"})).status_code == 401
    assert await db.scalar(select(Familia).where(Familia.usuario_id == me["id"])) is None
    assert (await db.execute(select(Integrante))).scalars().all() == []
    u = await db.get(Usuario, me["id"])
    assert u.email != "ana@familia-a.com" and u.password_hash is None and u.eliminado_en is not None
    assert _s3_en_memoria == {}
    act = await db.get(Actividad, actividad.id)
    await db.refresh(act)
    assert act.cupos_ocupados == 0  # cupo liberado


async def test_comentarios_pasan_por_moderacion(cliente, familia_a, familia_b, admin, asociacion, actividad):
    url = f"/api/v1/comentarios/actividad/{actividad.id}"
    r = await cliente.post(url, headers=familia_a, json={"texto": "¿Pueden ir niños de 5 años?"})
    assert r.status_code == 201 and r.json()["estado"] == "pendiente"
    cid = r.json()["id"]
    # la autora lo ve (pendiente); otra familia no
    assert (await cliente.get(url, headers=familia_a)).json()["total"] == 1
    assert (await cliente.get(url, headers=familia_b)).json()["total"] == 0
    # la asociación responde sin moderación
    r = await cliente.post(url, headers=asociacion, json={"texto": "Sí, desde 6 años con un adulto."})
    assert r.json()["estado"] == "aprobado"
    assert (await cliente.get(url, headers=familia_b)).json()["total"] == 1
    # admin aprueba el de la familia
    assert (await cliente.get("/api/v1/admin/comentarios", headers=admin)).json()["total"] == 1
    r = await cliente.post(f"/api/v1/admin/comentarios/{cid}/moderar", headers=admin, json={"aprobar": True})
    assert r.status_code == 200
    assert (await cliente.get(url, headers=familia_b)).json()["total"] == 2
    # B no puede borrar el comentario de A
    assert (await cliente.delete(f"/api/v1/comentarios/{cid}", headers=familia_b)).status_code == 404
    assert (await cliente.delete(f"/api/v1/comentarios/{cid}", headers=familia_a)).status_code == 200


async def test_likes(cliente, familia_a, familia_b, actividad):
    url = f"/api/v1/likes/actividad/{actividad.id}"
    assert (await cliente.put(url, headers=familia_a)).json()["likes"] == 1
    assert (await cliente.put(url, headers=familia_a)).json()["likes"] == 1  # idempotente
    assert (await cliente.put(url, headers=familia_b)).json()["likes"] == 2
    a = (await cliente.get(f"/api/v1/actividades/{actividad.id}", headers=familia_b)).json()
    assert a["likes"] == 2 and a["me_gusta"] is True
    assert (await cliente.delete(url, headers=familia_b)).json()["likes"] == 1
    import uuid
    assert (await cliente.put(f"/api/v1/likes/actividad/{uuid.uuid4()}", headers=familia_a)).status_code == 404


async def test_mensajes_solo_familia_asociacion(cliente, familia_a, familia_b, asociacion, admin, centro):
    # A inicia conversación con el centro
    r = await cliente.post("/api/v1/conversaciones", headers=familia_a, json={"centro_id": str(centro.id), "texto": "Hola, ¿hay cupo el sábado?"})
    assert r.status_code == 201
    conv = r.json()["id"]
    # la asociación la ve y responde
    lista = (await cliente.get("/api/v1/conversaciones", headers=asociacion)).json()
    assert len(lista) == 1 and lista[0]["no_leidos"] == 1
    r = await cliente.post(f"/api/v1/conversaciones/{conv}/mensajes", headers=asociacion, json={"texto": "Sí, quedan 3 lugares"})
    assert r.status_code == 201
    msgs = (await cliente.get(f"/api/v1/conversaciones/{conv}/mensajes", headers=familia_a)).json()
    assert [m["emisor_rol"] for m in msgs] == ["familia", "asociacion"] and msgs[0]["es_mio"]
    # la familia B NO puede leer ni escribir en la conversación de A
    assert (await cliente.get(f"/api/v1/conversaciones/{conv}/mensajes", headers=familia_b)).status_code == 404
    assert (await cliente.post(f"/api/v1/conversaciones/{conv}/mensajes", headers=familia_b, json={"texto": "intruso"})).status_code == 404
    # no existe forma de escribirle a otra familia: solo a centros verificados
    import uuid
    assert (await cliente.post("/api/v1/conversaciones", headers=familia_b, json={"centro_id": str(uuid.uuid4()), "texto": "hola"})).status_code == 404
    # la asociación no puede iniciar conversaciones (solo responder)
    assert (await cliente.post("/api/v1/conversaciones", headers=asociacion, json={"centro_id": str(centro.id), "texto": "hola"})).status_code == 403
    # admin supervisa pero no escribe
    assert (await cliente.get(f"/api/v1/conversaciones/{conv}/mensajes", headers=admin)).status_code == 200
    assert (await cliente.post(f"/api/v1/conversaciones/{conv}/mensajes", headers=admin, json={"texto": "x"})).status_code == 403
    # bloqueo por la familia
    assert (await cliente.post(f"/api/v1/conversaciones/{conv}/bloquear", headers=familia_a)).status_code == 200
    assert (await cliente.post(f"/api/v1/conversaciones/{conv}/mensajes", headers=asociacion, json={"texto": "¿sigues ahí?"})).status_code == 403
    # notificación al otro lado
    assert any(n["tipo"] == "mensaje" for n in (await cliente.get("/api/v1/me/notificaciones", headers=familia_a)).json())


async def test_gestion_catalogo_y_proyectos_recientes(cliente, admin, asociacion, centro):
    # asociación crea actividad, campaña y proyecto en su centro
    r = await cliente.post(f"/api/v1/gestion/centros/{centro.id}/actividades", headers=asociacion, json={
        "titulo": "Nueva visita", "categoria": "ninos", "fecha": str(date.today() + timedelta(days=10)), "hora_inicio": "10:00",
        "hora_fin": "12:00", "lugar": "Hospital", "descripcion": "Descripción de la nueva actividad.", "edad_minima": 6, "cupos_totales": 8})
    assert r.status_code == 201 and r.json()["cupos_disponibles"] == 8
    r = await cliente.post(f"/api/v1/gestion/centros/{centro.id}/campanas", headers=asociacion, json={
        "titulo": "Kits de higiene", "descripcion": "Jabón y pasta dental para el hospital.", "que_llevar": ["Jabón", "Pasta"],
        "donde_entregar": "Av. San Rafael 450", "horario_entrega": "Sábados 9-12"})
    assert r.status_code == 201
    p1 = (await cliente.post(f"/api/v1/gestion/centros/{centro.id}/proyectos", headers=asociacion, json={
        "titulo": "Proyecto viejo", "causa": "Niños", "objetivo": "100 niños", "descripcion": "Descripción del proyecto.", "avance": 0.2})).json()
    p2 = (await cliente.post(f"/api/v1/gestion/centros/{centro.id}/proyectos", headers=asociacion, json={
        "titulo": "Proyecto nuevo", "causa": "Niños", "objetivo": "200 niños", "descripcion": "Descripción del proyecto.", "avance": 0.1})).json()
    # RF-19: recientes primero
    lista = (await cliente.get("/api/v1/proyectos?orden=recientes", headers=asociacion)).json()["items"]
    assert [p["titulo"] for p in lista] == ["Proyecto nuevo", "Proyecto viejo"]
    # editar el viejo lo vuelve el más actualizado
    assert (await cliente.patch(f"/api/v1/gestion/proyectos/{p1['id']}", headers=asociacion, json={"avance": 0.5})).status_code == 200
    lista = (await cliente.get("/api/v1/proyectos?orden=actualizados", headers=asociacion)).json()["items"]
    assert lista[0]["titulo"] == "Proyecto viejo"
    assert (await cliente.get(f"/api/v1/proyectos?desde={p2['creado_en']}", headers=asociacion)).json()["total"] == 1
    # imagen de centro
    r = await cliente.put(f"/api/v1/gestion/centros/{centro.id}/imagen", headers=asociacion, files={"archivo": ("c.png", imagen_png(), "image/png")})
    assert r.status_code == 200 and r.json()["imagen_url"].startswith("/api/v1/archivos/centros/")
    assert (await cliente.get(r.json()["imagen_url"], headers=asociacion)).headers["content-type"] == "image/jpeg"
    # resumen admin
    res = (await cliente.get("/api/v1/gestion/resumen", headers=admin)).json()
    assert res["actividades_activas"] == 1


async def test_donacion_campana_una_vez(cliente, db, familia_a, centro):
    from app.models import Campana
    c = Campana(centro_id=centro.id, ciudad_id=centro.ciudad_id, titulo="Suma a su Mesa", descripcion="Alimentos para el asilo.", que_llevar=["Arroz"])
    db.add(c)
    await db.commit()
    r = await cliente.post("/api/v1/me/donaciones", headers=familia_a, json={"campana_id": str(c.id), "tipo": "Alimentos", "detalle": "10 kg de arroz"})
    assert r.status_code == 201
    r = await cliente.post("/api/v1/me/donaciones", headers=familia_a, json={"campana_id": str(c.id), "tipo": "Alimentos", "detalle": "otra vez"})
    assert r.status_code == 409
    camps = (await cliente.get("/api/v1/campanas", headers=familia_a)).json()["items"]
    assert camps[0]["ya_apoye"] is True and camps[0]["que_llevar"] == ["Arroz"]

"""RF-05 / RF-06 / RF-07(datos) / RF-13: cupos atómicos, idempotencia, edad mínima, cancelación, encuestas."""
import asyncio
from datetime import date, timedelta

from sqlalchemy import select

from app.models import Actividad
from tests.conftest import _actividad, crear_usuario, integrantes_de, login, auth


async def test_inscripcion_descuenta_cupos_por_persona(cliente, familia_a, actividad, db):
    ints = await integrantes_de(cliente, familia_a)
    elegibles = [i for i in ints if i["edad"] >= 6]  # Ana, Carlos, Sofía
    r = await cliente.post(f"/api/v1/actividades/{actividad.id}/inscripciones", headers=familia_a,
                           json={"integrantes_ids": [i["id"] for i in elegibles], "comentario": "Llevamos juguetes"})
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["personas"] == 3 and d["estado"] == "confirmada" and len(d["asistentes"]) == 3
    a = (await cliente.get(f"/api/v1/actividades/{actividad.id}", headers=familia_a)).json()
    assert a["cupos_ocupados"] == 3 and a["cupos_disponibles"] == 7
    # notificación generada
    n = (await cliente.get("/api/v1/me/notificaciones", headers=familia_a)).json()
    assert n and n[0]["tipo"] == "inscripcion"


async def test_edad_minima_se_valida_en_servidor(cliente, familia_a, actividad):
    ints = await integrantes_de(cliente, familia_a)
    mateo = next(i for i in ints if i["nombre"] == "Mateo")  # 4 años, mínimo 6
    r = await cliente.post(f"/api/v1/actividades/{actividad.id}/inscripciones", headers=familia_a,
                           json={"integrantes_ids": [mateo["id"]]})
    assert r.status_code == 422 and "edad mínima" in r.text


async def test_no_doble_inscripcion(cliente, familia_a, actividad):
    ints = await integrantes_de(cliente, familia_a)
    body = {"integrantes_ids": [ints[0]["id"]]}
    assert (await cliente.post(f"/api/v1/actividades/{actividad.id}/inscripciones", headers=familia_a, json=body)).status_code == 201
    r = await cliente.post(f"/api/v1/actividades/{actividad.id}/inscripciones", headers=familia_a, json=body)
    assert r.status_code == 409


async def test_ultimo_lugar_solo_lo_gana_una_familia(cliente, db, ciudad, centro):
    """RF-05 — criterio de aceptación: dos familias intentan el último lugar AL MISMO TIEMPO."""
    a = _actividad(centro, cupos_totales=5, cupos_ocupados=4)
    db.add(a)
    await db.commit()
    headers = []
    for i in range(4):
        await crear_usuario(db, f"fam{i}@x.com", ciudad=ciudad)
        headers.append(auth(await login(cliente, f"fam{i}@x.com")))
    bodies = []
    for h in headers:
        ints = await integrantes_de(cliente, h)
        bodies.append({"integrantes_ids": [ints[0]["id"]]})

    respuestas = await asyncio.gather(*[
        cliente.post(f"/api/v1/actividades/{a.id}/inscripciones", headers=h, json=b) for h, b in zip(headers, bodies)
    ])
    codigos = sorted(r.status_code for r in respuestas)
    assert codigos == [201, 409, 409, 409], codigos
    perdedor = next(r for r in respuestas if r.status_code == 409)
    assert "lugares" in perdedor.json()["error"]["mensaje"]  # aviso claro
    act = await db.get(Actividad, a.id)
    await db.refresh(act)
    assert act.cupos_ocupados == act.cupos_totales == 5  # nunca se sobrepasa


async def test_idempotencia_no_duplica(cliente, familia_a, actividad):
    ints = await integrantes_de(cliente, familia_a)
    body = {"integrantes_ids": [ints[0]["id"], ints[1]["id"]]}
    h = {**familia_a, "Idempotency-Key": "sync-offline-0001"}
    r1 = await cliente.post(f"/api/v1/actividades/{actividad.id}/inscripciones", headers=h, json=body)
    r2 = await cliente.post(f"/api/v1/actividades/{actividad.id}/inscripciones", headers=h, json=body)
    assert r1.status_code == r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"] and r2.headers["Idempotent-Replayed"] == "true"
    a = (await cliente.get(f"/api/v1/actividades/{actividad.id}", headers=familia_a)).json()
    assert a["cupos_ocupados"] == 2  # una sola vez
    # la clave es por usuario: otra ruta con la misma clave se rechaza
    r = await cliente.post("/api/v1/me/donaciones", headers=h, json={"centro_id": str(actividad.centro_id), "tipo": "Ropa", "detalle": "3 bolsas"})
    assert r.status_code == 422
    # formato inválido
    r = await cliente.post(f"/api/v1/actividades/{actividad.id}/inscripciones", headers={**familia_a, "Idempotency-Key": "x"}, json=body)
    assert r.status_code == 422


async def test_cancelar_libera_cupos(cliente, familia_a, actividad):
    ints = await integrantes_de(cliente, familia_a)
    ins = (await cliente.post(f"/api/v1/actividades/{actividad.id}/inscripciones", headers=familia_a,
                              json={"integrantes_ids": [ints[0]["id"], ints[1]["id"]]})).json()
    r = await cliente.post(f"/api/v1/me/inscripciones/{ins['id']}/cancelar", headers=familia_a)
    assert r.status_code == 200 and r.json()["estado"] == "cancelada"
    a = (await cliente.get(f"/api/v1/actividades/{actividad.id}", headers=familia_a)).json()
    assert a["cupos_ocupados"] == 0
    assert (await cliente.post(f"/api/v1/me/inscripciones/{ins['id']}/cancelar", headers=familia_a)).status_code == 409
    # puede volver a inscribirse
    assert (await cliente.post(f"/api/v1/actividades/{actividad.id}/inscripciones", headers=familia_a,
                               json={"integrantes_ids": [ints[0]["id"]]})).status_code == 201


async def test_actividad_pasada_o_cancelada_no_acepta(cliente, db, familia_a, centro):
    pasada = _actividad(centro, fecha=date.today() - timedelta(days=1))
    cancelada = _actividad(centro, estado="cancelada")
    db.add_all([pasada, cancelada])
    await db.commit()
    ints = await integrantes_de(cliente, familia_a)
    body = {"integrantes_ids": [ints[0]["id"]]}
    assert (await cliente.post(f"/api/v1/actividades/{pasada.id}/inscripciones", headers=familia_a, json=body)).status_code == 409
    assert (await cliente.post(f"/api/v1/actividades/{cancelada.id}/inscripciones", headers=familia_a, json=body)).status_code == 409
    # y no aparecen en el listado público
    lista = (await cliente.get("/api/v1/actividades", headers=familia_a)).json()
    assert all(x["estado"] == "activa" for x in lista["items"])


async def test_filtro_ciudad_rf02(cliente, db, ciudad, familia_a, centro):
    """Una familia de Monterrey nunca ve actividades de Hermosillo, y puede cambiar de ciudad."""
    from app.models import Ciudad, Centro, Categoria
    hmo = await db.scalar(select(Ciudad).where(Ciudad.clave == "hermosillo"))
    c_hmo = Centro(nombre="Comedor El Sol", tipo="Comedor", categoria=Categoria.comunidad, descripcion="Desayunos diarios en Hermosillo.",
                   direccion="Palo Verde", que_necesitan=[], acepta=[], verificado=True, ciudad_id=hmo.id)
    db.add(c_hmo)
    await db.flush()
    db.add(_actividad(c_hmo, titulo="Servir desayunos"))
    db.add(_actividad(centro, titulo="Visita MTY"))
    await db.commit()
    titulos = [x["titulo"] for x in (await cliente.get("/api/v1/actividades", headers=familia_a)).json()["items"]]
    assert "Visita MTY" in titulos and "Servir desayunos" not in titulos
    assert (await cliente.patch("/api/v1/me/familia", headers=familia_a, json={"ciudad": "hermosillo"})).status_code == 200
    titulos = [x["titulo"] for x in (await cliente.get("/api/v1/actividades", headers=familia_a)).json()["items"]]
    assert titulos == ["Servir desayunos"]
    assert (await cliente.patch("/api/v1/me/familia", headers=familia_a, json={"ciudad": "narnia"})).status_code == 422


async def test_encuestas_antes_y_despues(cliente, db, familia_a, actividad):
    ints = await integrantes_de(cliente, familia_a)
    ins = (await cliente.post(f"/api/v1/actividades/{actividad.id}/inscripciones", headers=familia_a,
                              json={"integrantes_ids": [ints[0]["id"]]})).json()
    url = f"/api/v1/me/inscripciones/{ins['id']}/encuesta"
    assert (await cliente.get("/api/v1/encuestas/antes", headers=familia_a)).json()["preguntas"]
    # validación de claves y escalas
    assert (await cliente.post(url, headers=familia_a, json={"momento": "antes", "respuestas": {"animo": 9}})).status_code == 422
    assert (await cliente.post(url, headers=familia_a, json={"momento": "antes", "respuestas": {"inventada": 1}})).status_code == 422
    # 'después' antes de la fecha → 409
    assert (await cliente.post(url, headers=familia_a, json={"momento": "despues", "respuestas": {"experiencia": 5}})).status_code == 409
    r = await cliente.post(url, headers=familia_a, json={"momento": "antes", "respuestas": {"animo": 5, "primera_vez": "si", "expectativa": "Convivir"}})
    assert r.status_code == 201
    assert (await cliente.post(url, headers=familia_a, json={"momento": "antes", "respuestas": {"animo": 4}})).status_code == 409
    # la actividad pasa → 'después' permitido, y queda asociada a la inscripción
    act = await db.get(Actividad, actividad.id)
    act.fecha = date.today() - timedelta(days=1)
    await db.commit()
    r = await cliente.post(url, headers=familia_a, json={"momento": "despues", "respuestas": {"experiencia": 5, "repetiria": 5, "recomendaria": "si"}})
    assert r.status_code == 201
    d = (await cliente.get(f"/api/v1/me/inscripciones/{ins['id']}", headers=familia_a)).json()
    assert d["encuesta_antes"] and d["encuesta_despues"]
    assert len((await cliente.get(f"/api/v1/me/inscripciones/{ins['id']}/encuestas", headers=familia_a)).json()) == 2


async def test_asistencia_alimenta_historial_e_insignias(cliente, db, familia_a, asociacion, actividad):
    ints = await integrantes_de(cliente, familia_a)
    ins = (await cliente.post(f"/api/v1/actividades/{actividad.id}/inscripciones", headers=familia_a,
                              json={"integrantes_ids": [ints[0]["id"], ints[2]["id"]]})).json()
    lista = (await cliente.get(f"/api/v1/gestion/actividades/{actividad.id}/asistentes", headers=asociacion)).json()
    assert lista[0]["familia_nombre"].startswith("Familia") and {x["nombre"] for x in lista[0]["asistentes"]} == {"Ana", "Sofía"}
    assert (await cliente.get("/api/v1/me/insignias", headers=familia_a)).json()["actividades_completadas"] == 0
    r = await cliente.post(f"/api/v1/gestion/actividades/{actividad.id}/asistencia", headers=asociacion, json={"asistieron": [ins["id"]]})
    assert r.status_code == 200
    ins_ = (await cliente.get("/api/v1/me/insignias", headers=familia_a)).json()
    assert ins_["actividades_completadas"] == 1 and ins_["nivel"] == "Brote"
    assert next(i for i in ins_["insignias"] if i["clave"] == "primer_paso")["obtenida"] is True
    hist = (await cliente.get("/api/v1/me/inscripciones", headers=familia_a)).json()
    assert hist[0]["estado"] == "asistio"


async def test_sync_para_cache_offline(cliente, db, familia_a, centro, actividad):
    r = await cliente.get("/api/v1/sync", headers=familia_a)
    assert r.status_code == 200
    d = r.json()
    assert d["ciudad"] == "monterrey" and len(d["actividades"]) == 1 and len(d["centros"]) == 1
    marca = d["marca"]
    r = await cliente.get("/api/v1/sync", headers=familia_a, params={"desde": marca})
    assert r.json()["actividades"] == [] and r.json()["centros"] == []
    # un cambio posterior sí aparece (incluida una cancelación, para que la app la retire)
    act = await db.get(Actividad, actividad.id)
    act.estado = "cancelada"
    await db.commit()
    r = await cliente.get("/api/v1/sync", headers=familia_a, params={"desde": marca})
    assert [x["estado"] for x in r.json()["actividades"]] == ["cancelada"]

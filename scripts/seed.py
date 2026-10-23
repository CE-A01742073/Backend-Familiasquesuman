"""Carga inicial con datos realistas del dominio (Monterrey y Hermosillo).
Uso:  python -m scripts.seed            (idempotente: no duplica si ya hay datos)
      python -m scripts.seed --demo     (además crea familias y cuentas de prueba)
"""
import argparse
import asyncio
import os
import secrets
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import (
    Actividad,
    AvisoPrivacidad,
    Campana,
    Categoria,
    Centro,
    Ciudad,
    EstadoInscripcion,
    Familia,
    Inscripcion,
    Integrante,
    Proyecto,
    Rol,
    Usuario,
)
from app.models.participacion import Asistente
from scripts.aviso_privacidad import AVISO_V1

HOY = date.today()


def sab(n: int) -> date:
    """n-ésimo sábado a partir de hoy."""
    d = HOY + timedelta(days=(5 - HOY.weekday()) % 7 or 7)
    return d + timedelta(weeks=n)


CENTROS = [
    # (clave_ciudad, nombre, tipo, categoria, descripcion, direccion, horario, necesitan, acepta, tel, wa)
    ("monterrey", "VIFAC", "Albergue", Categoria.comunidad,
     "Residencia donde atienden y capacitan a mujeres en estado vulnerable durante su embarazo. Ofrecen casa y alimento.",
     "Gral. Ignacio Zaragoza 625 Sur, La Pastora, Guadalupe", "Lunes a viernes 10:00–17:00",
     ["Ropa", "Alimentos", "Higiene"], ["ropa", "alimentos", "higiene"], "8183551100", None),
    ("monterrey", "Morada del Anciano Desvalido de Cadereyta", "Asilo de ancianos", Categoria.adultos_mayores,
     "Asilo donde se atiende a 47 adultos indigentes o de escasos recursos. Se les brinda casa, alimentación y atención.",
     "Blvd. José María González #1000, Cadereyta", "Sábados y domingos 10:00–14:00",
     ["Alimentos", "Higiene", "Camas hospitalarias", "Sillas de ruedas", "Cobijas"],
     ["alimentos", "higiene", "sillas_ruedas", "cobijas"], "8282840123", "8282840123"),
    ("monterrey", "Hogar de la Misericordia", "Casa hogar", Categoria.ninos,
     "Casa hogar de adolescentes y adultos con parálisis cerebral. Reciben visitas familiares para convivencia y apoyo.",
     "Col. Mitras Centro, Monterrey", "Sábados 10:00–13:00",
     ["Higiene", "Ropa", "Sillas de ruedas"], ["higiene", "ropa", "sillas_ruedas"], "8183460000", "8183460000"),
    ("monterrey", "Forma-T", "Asociación civil", Categoria.ninos,
     "Programas educativos y de formación para niñas, niños y jóvenes en comunidades vulnerables de Monterrey.",
     "Col. Independencia, Monterrey", "Sábados 9:00–12:00",
     ["Útiles escolares", "Juguetes", "Cuentos infantiles"], ["utiles", "juguetes"], "8181234504", "8181234504"),
    ("monterrey", "Escucha Corazón", "Asociación civil", Categoria.comunidad,
     "Acompañamiento que marca una profunda diferencia: apoyo emocional y escucha para personas en situación vulnerable.",
     "Col. Del Valle, San Pedro Garza García", "Con cita",
     ["Voluntarios para acompañamiento"], [], "8181234505", None),
    ("monterrey", "Cíclica", "Asociación civil", Categoria.medio_ambiente,
     "Reciclaje y economía circular: recolección de materiales y talleres ambientales para familias.",
     "Col. Contry, Monterrey", "Sábados 9:00–12:00",
     ["Materiales reciclables", "Voluntarios para talleres"], [], "8181234506", None),
    ("monterrey", "Regalando Estrellas", "Asociación civil", Categoria.ninos,
     "Visitas al Hospital Materno Infantil llevando desayunos, regalos, juguetes y kits de higiene personal a las familias.",
     "Av. San Rafael No. 450, Guadalupe", "Visitas programadas",
     ["Juguetes", "Kits de higiene", "Desayunos"], ["juguetes", "higiene", "alimentos"], "8181234507", "8181234507"),
    ("monterrey", "Trazo", "Asociación civil", Categoria.comunidad,
     "Grupo de mujeres voluntarias que realiza visitas quincenales al Centro de Reinserción Social de Escobedo para acompañar a mujeres privadas de la libertad mediante pláticas y talleres.",
     "Escobedo, N.L.", "Visitas quincenales", ["Productos de higiene", "Ropa"], ["higiene", "ropa"], "8181234508", None),
    ("monterrey", "DIF San Pedro", "Institución pública", Categoria.adultos_mayores,
     "Voluntariado DIF Te Acompaña: acompañamiento a adultos mayores y jóvenes en soledad, con discapacidad o con una red de apoyo reducida.",
     "San Pedro Garza García", "Lunes a viernes 9:00–16:00",
     ["Cobijas", "Alimentos", "Voluntarios para visitas"], ["cobijas", "alimentos"], "8184004000", None),
    ("monterrey", "Cocinando de Corazón a Corazón", "Comedor comunitario", Categoria.comunidad,
     "Comedor comunitario diocesano que lleva alimento y esperanza a personas y familias en situación vulnerable. A través de una red de parroquias, los alimentos preparados se distribuyen en distintas zonas.",
     "Col. Centro, Monterrey", "Lunes a sábado 8:00–12:00",
     ["Alimentos no perecederos", "Voluntarios para cocinar"], ["alimentos"], "8181234510", "8181234510"),
    ("monterrey", "Refugio Patitas Regias", "Refugio animal", Categoria.animales,
     "Refugio de perros y gatos rescatados. Reciben familias para pasear, bañar y socializar a los animales en adopción.",
     "Col. Cumbres, Monterrey", "Sábados y domingos 9:00–13:00",
     ["Croquetas", "Cobijas", "Voluntarios para paseos"], ["croquetas", "cobijas"], "8181234511", "8181234511"),
    ("hermosillo", "Comedor Comunitario El Sol", "Comedor comunitario", Categoria.comunidad,
     "Comedor que sirve 200 desayunos diarios en Hermosillo.", "Col. Palo Verde, Hermosillo", "Lunes a sábado 7:00–10:00",
     ["Arroz y frijol", "Voluntarios para servir"], ["alimentos"], "6621234511", "6621234511"),
    ("hermosillo", "Casa Hogar Luz del Desierto", "Casa hogar", Categoria.ninos,
     "Casa hogar para niñas y niños en situación de vulnerabilidad. Reciben familias para tardes de juego y apoyo escolar.",
     "Col. Las Quintas, Hermosillo", "Sábados 10:00–13:00",
     ["Útiles escolares", "Ropa", "Juguetes"], ["utiles", "ropa", "juguetes"], "6621234512", "6621234512"),
    ("hermosillo", "Verde Sonora", "Asociación civil", Categoria.medio_ambiente,
     "Reforestación urbana y limpieza de arroyos con familias voluntarias.", "Parque Madero, Hermosillo", "Domingos 7:00–10:00",
     ["Árboles nativos", "Guantes y bolsas"], [], "6621234513", None),
]

# (centro_idx, titulo, categoria, fecha, hora_inicio, hora_fin, lugar, descripcion, requisitos, edad_min, apta_ninos, cupos_tot, cupos_ocup)
ACTIVIDADES = [
    (6, "Regalando Estrellas: visita al Materno Infantil", Categoria.ninos, sab(0), time(9, 45), time(12, 0),
     "Hospital Materno Infantil, Guadalupe", "Entrega de aproximadamente 200 desayunos. Entrega de regalos, juguetes y kits de higiene personal a las familias del hospital.",
     ["Aportación en especie", "Llegar 15 minutos antes"], 6, True, 12, 12),
    (1, "Visita a la Morada del Anciano", Categoria.adultos_mayores, sab(1) + timedelta(days=1), time(11, 0), time(13, 0),
     "Blvd. José María González #1000, Cadereyta", "Una mañana de convivencia, lotería y pláticas con los 47 residentes del asilo. Se agradece llevar alimentos o productos de higiene.",
     ["Cubrebocas", "Puntualidad"], 5, True, 20, 6),
    (2, "Tarde de juegos en Hogar de la Misericordia", Categoria.ninos, sab(1), time(10, 0), time(13, 0),
     "Col. Mitras Centro, Monterrey", "Convivencia con los residentes de la casa hogar: juegos de mesa, música y manualidades.",
     ["Llevar identificación", "Ropa cómoda"], 6, True, 16, 9),
    (5, "Taller de reciclaje en familia", Categoria.medio_ambiente, sab(1), time(9, 0), time(11, 0),
     "Col. Contry, Monterrey", "Aprende a separar residuos y a darles una segunda vida. Cada familia se lleva su propio contenedor.",
     ["Llevar 5 envases limpios"], 5, True, 30, 8),
    (9, "Servir en Cocinando de Corazón a Corazón", Categoria.comunidad, sab(2) - timedelta(days=1), time(16, 0), time(18, 0),
     "Col. Centro, Monterrey", "Ayuda a preparar y empacar los alimentos que se distribuyen a través de la red de parroquias.",
     ["Cabello recogido", "Zapatos cerrados"], 10, True, 15, 5),
    (3, "Cuentacuentos con Forma-T", Categoria.ninos, sab(2), time(10, 0), time(12, 0),
     "Col. Independencia, Monterrey", "Lee cuentos a los más pequeños y ayuda con una manualidad. Trae tu libro favorito de la infancia.",
     ["Llevar un libro infantil"], 4, True, 12, 2),
    (10, "Paseo de perritos en Patitas Regias", Categoria.animales, sab(2) + timedelta(days=1), time(9, 0), time(11, 0),
     "Col. Cumbres, Monterrey", "Pasea, baña y juega con los perros del refugio. Ideal para niños que quieren una mascota.",
     ["Ropa que se pueda ensuciar"], 6, True, 10, 3),
    (8, "Visita a adultos mayores con DIF Te Acompaña", Categoria.adultos_mayores, sab(3), time(10, 0), time(12, 0),
     "San Pedro Garza García", "Acompaña a una persona mayor en soledad: plática, juegos de mesa y un cafecito.",
     ["Identificación oficial del adulto"], 8, True, 12, 0),
    (11, "Servir desayunos", Categoria.comunidad, sab(0), time(7, 0), time(10, 0),
     "Col. Palo Verde, Hermosillo", "Ayuda a servir y limpiar en el comedor comunitario.", ["Cabello recogido", "Zapatos cerrados"], 10, True, 10, 4),
    (12, "Tarde de juegos en Luz del Desierto", Categoria.ninos, sab(1), time(10, 0), time(13, 0),
     "Col. Las Quintas, Hermosillo", "Juegos, pintura y apoyo con tareas para los niños de la casa hogar.", ["Ropa cómoda"], 5, True, 14, 6),
    (13, "Reforestación en Parque Madero", Categoria.medio_ambiente, sab(2) + timedelta(days=1), time(7, 0), time(10, 0),
     "Parque Madero, Hermosillo", "Siembra de árboles nativos y limpieza del arroyo. Llevar gorra y agua.", ["Gorra", "Agua"], 4, True, 40, 11),
]

CAMPANAS = [
    (1, "Suma a su Mesa", "Recolección de alimentos y productos de limpieza para el Asilo de Ancianos Morada del Anciano Desvalido de Cadereyta. Se sirven 6,900 servicios de alimentación al mes.",
     ["Arroz", "Frijol", "Aceite", "Cloro", "Jabón"], "Blvd. José María González #1000, Cadereyta", "Sábados y domingos 10:00–14:00", HOY + timedelta(days=16)),
    (3, "Bibliotecas Infantiles", "Recolección de cuentos infantiles para crear bibliotecas en casas hogar y centros comunitarios.",
     ["Cuentos infantiles nuevos o en buen estado"], "Col. Independencia, Monterrey", "Sábados 9:00–12:00", HOY + timedelta(days=32)),
    (6, "Kits de higiene para el Materno Infantil", "Jabón, pasta dental, toallas y pañales para las familias que Regalando Estrellas visita cada mes en el hospital.",
     ["Jabón", "Pasta dental", "Toallas", "Pañales"], "Av. San Rafael No. 450, Guadalupe", "Visitas programadas", HOY + timedelta(days=48)),
    (10, "Cobijas para el refugio", "Con el frío los perros y gatos del refugio necesitan cobijas y croquetas.",
     ["Cobijas", "Croquetas"], "Col. Cumbres, Monterrey", "Sábados y domingos 9:00–13:00", HOY + timedelta(days=60)),
    (11, "Desayunos que Suman", "Arroz, frijol y aceite para el comedor comunitario.", ["Arroz", "Frijol", "Aceite"],
     "Col. Palo Verde, Hermosillo", "Lunes a sábado 7:00–10:00", HOY + timedelta(days=17)),
]

PROYECTOS = [
    (7, "Trazo… Escribiendo una nueva historia", "Mujeres", "25 mujeres acompañadas",
     "Somos un grupo de mujeres voluntarias que realizamos visitas quincenales al Centro de Reinserción Social de Escobedo para acompañar a mujeres privadas de la libertad mediante pláticas de desarrollo humano y talleres.", 0.5),
    (8, "Voluntariado DIF Te Acompaña", "Adultos mayores", "200 adultos mayores acompañados",
     "Acompañar a adultos mayores o jóvenes vulnerables, en soledad, con discapacidad o con una red de apoyo reducida. Realizar visitas en familia mínimo una vez cada 15 días.", 0.35),
    (9, "Cocinando de Corazón a Corazón", "Alimentación", "Red de parroquias con comedor",
     "Comedor comunitario diocesano que lleva alimento y esperanza a personas y familias en situación vulnerable. A través de una red de parroquias, los alimentos preparados se distribuyen en distintas zonas de la ciudad.", 0.7),
    (13, "Un árbol por familia", "Medio ambiente", "1,000 árboles sembrados en Hermosillo",
     "Cada familia voluntaria adopta y cuida un árbol nativo durante un año. Llevamos 410.", 0.41),
]


async def main(demo: bool) -> None:
    async with SessionLocal() as db:
        if await db.scalar(select(Ciudad.id).limit(1)):
            print("Ya hay datos; no se vuelve a sembrar el catálogo.")
            ciudades = {c.clave: c for c in (await db.execute(select(Ciudad))).scalars()}
            centros = list((await db.execute(select(Centro).order_by(Centro.creado_en))).scalars())
        else:
            ciudades = {
                "monterrey": Ciudad(clave="monterrey", nombre="Monterrey", estado="Nuevo León"),
                "hermosillo": Ciudad(clave="hermosillo", nombre="Hermosillo", estado="Sonora"),
            }
            db.add_all(ciudades.values())
            await db.flush()

            centros = []
            for (cc, nombre, tipo, cat, desc, dirc, hor, nec, ace, tel, wa) in CENTROS:
                c = Centro(nombre=nombre, tipo=tipo, categoria=cat, descripcion=desc, direccion=dirc, horario_visitas=hor,
                           que_necesitan=nec, acepta=ace, telefono=tel, whatsapp=wa, verificado=True, ciudad_id=ciudades[cc].id,
                           correo=f"contacto@{nombre.split()[0].lower().replace('-', '')}.org.mx")
                db.add(c)
                centros.append(c)
            await db.flush()

            for (ci, tit, cat, fecha, hi, hf, lugar, desc, req, edad, apta, tot, ocu) in ACTIVIDADES:
                c = centros[ci]
                db.add(Actividad(centro_id=c.id, ciudad_id=c.ciudad_id, titulo=tit, categoria=cat, fecha=fecha, hora_inicio=hi, hora_fin=hf,
                                 lugar=lugar, descripcion=desc, requisitos=req, edad_minima=edad, apta_ninos=apta,
                                 cupos_totales=tot, cupos_ocupados=ocu))
            for (ci, tit, desc, llevar, donde, hor, hasta) in CAMPANAS:
                c = centros[ci]
                db.add(Campana(centro_id=c.id, ciudad_id=c.ciudad_id, titulo=tit, descripcion=desc, que_llevar=llevar,
                               donde_entregar=donde, horario_entrega=hor, hasta=hasta))
            for (ci, tit, causa, obj, desc, av) in PROYECTOS:
                db.add(Proyecto(centro_id=centros[ci].id, titulo=tit, causa=causa, objetivo=obj, descripcion=desc, avance=av))

            db.add(AvisoPrivacidad(version="1.0", contenido=AVISO_V1, publicado_en=datetime.now(timezone.utc)))
            await db.flush()
            print(f"Catálogo sembrado: {len(ciudades)} ciudades, {len(centros)} centros, {len(ACTIVIDADES)} actividades, "
                  f"{len(CAMPANAS)} campañas, {len(PROYECTOS)} proyectos, aviso de privacidad v1.0")

        # Administrador inicial (siempre): la contraseña viene de variable de entorno o se genera.
        admin_email = os.environ.get("ADMIN_EMAIL", "admin@familiasquesuman.com").lower()
        if not await db.scalar(select(Usuario.id).where(Usuario.email == admin_email)):
            pwd = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(14)
            db.add(Usuario(email=admin_email, password_hash=hash_password(pwd), nombre="Equipo Familias que Suman", rol=Rol.admin))
            print(f"Admin creado: {admin_email}  contraseña: {pwd}   ← guárdala, no se vuelve a mostrar")

        if demo:
            await _demo(db, ciudades, centros)
        await db.commit()


async def _demo(db, ciudades, centros) -> None:
    """Cuentas de prueba para la demo. Contraseña común: ver salida."""
    pwd = os.environ.get("DEMO_PASSWORD", "FamiliasDemo2026!")
    h = hash_password(pwd)
    creados = []

    async def usuario(email, nombre, rol, **kw):
        u = await db.scalar(select(Usuario).where(Usuario.email == email))
        if u is None:
            u = Usuario(email=email, password_hash=h, nombre=nombre, rol=rol, **kw)
            db.add(u)
            await db.flush()
            creados.append(email)
        return u

    # Asociaciones: una cuenta por centro de ejemplo
    await usuario("regalando.estrellas@demo.familiasquesuman.com", "Regalando Estrellas", Rol.asociacion, centro_id=centros[6].id)
    await usuario("morada.anciano@demo.familiasquesuman.com", "Morada del Anciano", Rol.asociacion, centro_id=centros[1].id)
    await usuario("comedor.elsol@demo.familiasquesuman.com", "Comedor El Sol", Rol.asociacion, centro_id=centros[11].id)

    # Familias
    familias = [
        ("familia.ramirez@demo.familiasquesuman.com", "Ana Ramírez", "Familia Ramírez", "San Pedro Garza García", "monterrey",
         [("Ana", 41), ("Carlos", 43), ("Sofía", 12), ("Mateo", 8)]),
        ("familia.garza@demo.familiasquesuman.com", "Luis Garza", "Familia Garza", "Guadalupe", "monterrey",
         [("Luis", 38), ("Marcela", 36), ("Regina", 7)]),
        ("familia.lopez@demo.familiasquesuman.com", "Patricia López", "Familia López", "Col. Centenario", "hermosillo",
         [("Patricia", 45), ("Diego", 15), ("Valeria", 11)]),
    ]
    for email, nombre, fam_nombre, zona, ciudad, integrantes in familias:
        u = await usuario(email, nombre, Rol.familia)
        if not await db.scalar(select(Familia.id).where(Familia.usuario_id == u.id)):
            f = Familia(usuario_id=u.id, nombre=fam_nombre, zona=zona, ciudad_id=ciudades[ciudad].id)
            f.integrantes = [Integrante(nombre=n, edad=e) for n, e in integrantes]
            db.add(f)
    await db.flush()

    # Historial: la familia Ramírez ya asistió a una actividad pasada (para insignias y testimonios)
    ram = await db.scalar(select(Familia).where(Familia.nombre == "Familia Ramírez"))
    pasada = await db.scalar(select(Actividad).where(Actividad.titulo == "Servir en Cocinando de Corazón a Corazón"))
    if ram and pasada and not await db.scalar(select(Inscripcion.id).where(Inscripcion.familia_id == ram.id)):
        hist = Actividad(centro_id=pasada.centro_id, ciudad_id=pasada.ciudad_id, titulo="Servir desayunos de domingo", categoria=Categoria.comunidad,
                         fecha=HOY - timedelta(days=21), hora_inicio=time(8, 0), hora_fin=time(11, 0), lugar=pasada.lugar,
                         descripcion="Preparación y entrega de desayunos a familias de la Col. Centro.", requisitos=[], edad_minima=8,
                         cupos_totales=15, cupos_ocupados=12, estado="finalizada")
        db.add(hist)
        await db.flush()
        ins = Inscripcion(actividad_id=hist.id, familia_id=ram.id, personas=2, estado=EstadoInscripcion.asistio)
        ins.asistentes = [Asistente(nombre="Ana", edad=41), Asistente(nombre="Carlos", edad=43)]
        db.add(ins)

    if creados:
        print(f"Cuentas demo creadas ({len(creados)}), contraseña: {pwd}")
        for e in creados:
            print("  ", e)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--demo", action="store_true", help="crear cuentas y familias de prueba")
    asyncio.run(main(p.parse_args().demo))

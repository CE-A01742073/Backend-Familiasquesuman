"""Datos reales tomados de familiasquesuman.com (con permiso) + historial para la demo.
Se corre DESPUÉS de scripts.seed, sobre la base ya sembrada, y es idempotente.

  python -m scripts.datos_reales                       # centros, actividades, campañas y proyectos reales + fotos
  python -m scripts.datos_reales --familia correo@x.com # además, historial completo para esa familia (insignias, encuestas,
                                                       # testimonios, comentarios, likes, donaciones, notificaciones)
  python -m scripts.datos_reales --sin-fotos           # no descarga imágenes (sin internet)

Las fotos se descargan del sitio y se guardan en MinIO con las mismas reglas que las subidas desde la app.
"""
import argparse
import asyncio
import random
from datetime import date, datetime, time, timedelta, timezone

import requests
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.core import storage
from app.db.session import SessionLocal, engine
from app.models import (
    Actividad,
    Campana,
    Categoria,
    Centro,
    Ciudad,
    Comentario,
    EstadoInscripcion,
    Familia,
    Inscripcion,
    Like,
    Proyecto,
    TipoObjetivo,
    Usuario,
)
from app.models.catalogo import EstadoActividad
from app.models.participacion import (
    Asistente,
    Donacion,
    EncuestaRespuesta,
    EstadoModeracion,
    Momento,
    Notificacion,
    Testimonio,
)

HOY = date.today()
B44 = "https://base44.app/api/apps/69ed00f78e8b6884c29526e1/files/mp/public/69ed00f78e8b6884c29526e1/"
MEDIA = "https://media.base44.com/images/public/69ed00f78e8b6884c29526e1/"

# ---------- Centros (directorio y "Quiero donar" del sitio) ----------
# clave = nombre tal como quedó en seed.py (si existe se actualiza; si no, se crea)
CENTROS = {
    "Morada del Anciano Desvalido de Cadereyta": dict(
        tipo="Asilo de ancianos", categoria=Categoria.adultos_mayores,
        descripcion="Atención a adultos mayores en abandono, soledad y falta de apoyo familiar. Se les proporciona una vida digna: refugio, alimentación, atención integral y compañía las 24 horas a 46 adultos mayores. Hablar con anticipación para ver qué actividades se recomiendan y en qué horario.",
        direccion="Blvd. José María González #1000, Cadereyta", horario_visitas="Con cita previa",
        que_necesitan=["Azúcar, leche, aceite, té y gelatina", "Mole en lata, saladitas y servilletas", "Ensure, jugos y frutas",
                       "Trapeadores, cubetas y botes de basura", "Cloro, Fabuloso, pino y jabón líquido", "Guantes, shampoo y bolsas de basura"],
        acepta=["alimentos", "higiene", "sillas_ruedas", "cobijas"], telefono="8282844311", whatsapp="3318290852",
        imagen=B44 + "6d3492449_4f610831-7c0a-491a-87af-dad6409e9d8e.png",
    ),
    "Hogar de la Misericordia": dict(
        tipo="Casa hogar", categoria=Categoria.comunidad,
        descripcion="Hogar de la Misericordia ofrece vida digna a personas con enfermedades irreversibles y/o terminales no contagiosas, en completo desamparo y sin recursos económicos. Brinda albergue, vestido, alimentación, medicamentos, terapias y atención médica, dental y de enfermería. Se aceptan visitas de niños y adultos con previo aviso; se recomienda llevar una actividad planeada y no más de 15 personas por visita.",
        direccion="Calle 20 de Noviembre #200, Col. Ildefonso Vázquez, Santa Catarina", horario_visitas="Con previo aviso y agenda",
        que_necesitan=["Pañales de adulto mediano y grande", "Aceite, atún, azúcar, sal y galletas maría", "Arroz, pasta, frijol y leche deslactosada",
                       "Fabuloso, pinol y bolsas de basura jumbo", "Jabón de manos, de trastes y papel sanitario", "Ropa de jóvenes y adultos"],
        acepta=["alimentos", "higiene", "ropa", "sillas_ruedas"], telefono="8183368767", whatsapp=None,
        imagen=B44 + "6b205f6b9_Capturadepantalla2026-05-27alas43501pm.png",
    ),
    "VIFAC": dict(
        tipo="Albergue", categoria=Categoria.comunidad,
        descripcion="Residencia donde atienden y capacitan a mujeres en estado vulnerable durante su embarazo. Ofrecen casa y alimento durante el embarazo y unos meses posteriores al nacimiento.",
        direccion="Gral. Ignacio Zaragoza 625 Sur, La Pastora, 67140 Guadalupe, N.L.", horario_visitas="Lunes a viernes 10:00–17:00",
        que_necesitan=["Ropa de bebé y de mamá", "Alimentos no perecederos", "Pañales y productos de higiene"],
        acepta=["ropa", "alimentos", "higiene"], telefono="8181912040", whatsapp=None,
        imagen=MEDIA + "01cfd5a19_230870A6-5ACE-4EDD-AC42-6D7787130346.png",
    ),
    "La Gran Familia": dict(
        ciudad="monterrey", tipo="Casa hogar", categoria=Categoria.ninos,
        descripcion="La Gran Familia es una casa hogar que atiende desde hace 44 años a niños, niñas y adolescentes que fueron retirados de sus familias por falta de cuidados parentales. Ofrece vivienda, alimentación, educación y salud. Solo adultos para visitas internas; se requiere organización previa con la institución y se recomienda llevar una actividad para los niños: dinámicas, juegos, manualidades o lectura.",
        direccion="Carretera Nacional Km 255, Col. Los Rodríguez, Villa de Santiago", horario_visitas="Con calendario confirmado",
        que_necesitan=["Visitas con actividades de integración", "Alimentos y productos de limpieza", "Ropa e higiene personal",
                       "Útiles escolares", "Tenis blancos y zapato escolar"],
        acepta=["ropa", "alimentos", "higiene", "utiles"], telefono=None, whatsapp="8126240294",
        imagen=B44 + "8666a1f17_2CD95152-0A8D-445A-BB8E-B7DF7B0C327A.png",
    ),
    "Apadrina un Niño": dict(
        ciudad="monterrey", tipo="Albergue", categoria=Categoria.ninos,
        descripcion="Albergue donde pueden hospedarse sin costo niños que vienen a Monterrey a tratamiento de cáncer, junto con un adulto cuidador. Recibe a 40 niños y sirve unas 200 comidas diarias de lunes a viernes. Se buscan voluntarios para servir comida de 1:00 a 3:00; puede asistirse por día. No es necesario llevar donaciones para visitar; se recomienda avisar antes.",
        direccion="Cuautla 208, Col. 5 de Mayo, 64186 Monterrey, N.L.", horario_visitas="Lunes a viernes 13:00–15:00 (comedor)",
        que_necesitan=["Alimentos no perecederos", "Productos de higiene personal", "Ropa de niño y adulto", "Productos de limpieza",
                       "Ropa de cama individual", "Pañales y toallas húmedas", "Juguetes", "Voluntarios para el comedor"],
        acepta=["juguetes", "ropa", "alimentos", "higiene"], telefono="8131117884", whatsapp="8131117884",
        imagen=B44 + "958716f43_PHOTO-2026-05-07-18-49-24.jpg",
    ),
    "Comedor Apadrina un Niño": dict(
        ciudad="monterrey", tipo="Comedor", categoria=Categoria.comunidad,
        descripcion="Comedor para apoyar a las familias de pacientes internados en la Clínica 25 del IMSS. Sirve aproximadamente 200 comidas de lunes a viernes de 1:00 a 3:00 pm. Adultos y niños bienvenidos; hablar antes para confirmar asistencia.",
        direccion="Cuautla #208, Col. 5 de Mayo, Monterrey", horario_visitas="Lunes a viernes 13:00–15:00",
        que_necesitan=["Desechables", "Alimentos no perecederos", "Voluntarios para servir"],
        acepta=["alimentos"], telefono="8131117884", whatsapp="8131117884",
        imagen=B44 + "e4751cf9f_PHOTO-2026-05-07-18-49-24.jpg",
    ),
    "Asistencia y Ropero del Pobre": dict(
        ciudad="monterrey", tipo="Asilo de ancianos", categoria=Categoria.adultos_mayores,
        descripcion="Asociación civil con 81 años de labor que brinda atención integral y permanente a 104 adultos mayores en situación vulnerable, muchos de ellos sin familia ni pensión.",
        direccion="Hidalgo Sur #637, Zona Centro, Saltillo, Coahuila", horario_visitas="Con cita previa",
        que_necesitan=["Ropa de adulto mayor", "Alimentos no perecederos", "Productos de higiene", "Sillas de ruedas"],
        acepta=["ropa", "alimentos", "higiene", "sillas_ruedas", "cobijas"], telefono="8111069946", whatsapp="8111069946",
        imagen=B44 + "cbca106e4_PHOTO-2026-09-25-10-14-12.jpg",
    ),
    "Familia Viva": dict(
        ciudad="monterrey", tipo="Asociación civil", categoria=Categoria.ninos,
        descripcion="Familia Viva detectó la necesidad de contar con más libros y espacios de lectura en escuelas públicas. De ahí nació la campaña para recolectar cuentos infantiles y armar salitas de lectura que se donan a colegios e instituciones con niños.",
        direccion="Monterrey, N.L.", horario_visitas="Con cita",
        que_necesitan=["Cuentos de preescolar, primaria y secundaria", "Libreros"], acepta=["utiles"], telefono="8180296174", whatsapp="8180296174",
        imagen=B44 + "1bff8e704_Capturadepantalla2026-05-12alas75105pm.png",
    ),
    "Familia Misionera": dict(
        ciudad="monterrey", tipo="Grupo de voluntariado", categoria=Categoria.comunidad,
        descripcion="Misiones en familia por el día: visita a las familias de la colonia San Gilberto, en Santa Catarina, con convivencia, pláticas y un tema distinto cada mes.",
        direccion="Bahía de La Paz 223, San Gilberto, 66369 Santa Catarina, N.L.", horario_visitas="Un sábado al mes 9:30–13:00",
        que_necesitan=["Familias voluntarias", "Despensas para las familias visitadas"], acepta=["alimentos", "ropa"], telefono=None, whatsapp="8120322281",
        imagen=B44 + "23d529f42_images.jpg",
    ),
    # Solo foto para los que ya existen
    "Regalando Estrellas": dict(imagen=B44 + "a5c31e1a6_Capturadepantalla2026-05-12alas75712pm.png"),
    "Cíclica": dict(imagen=B44 + "a1ec33aea_PHOTO-2026-05-30-14-42-53.jpg"),
    "Forma-T": dict(imagen=B44 + "154fb03a1_PHOTO-2026-06-12-14-13-07.jpg"),
    "Escucha Corazón": dict(imagen=B44 + "95d3573ab_0.png"),
    "Trazo": dict(imagen=B44 + "621cf18ba_PHOTO-2026-09-23-13-44-53.jpg"),
    "DIF San Pedro": dict(imagen=B44 + "6e20d15fd_PHOTO-2026-07-20-14-06-17.jpg"),
    "Cocinando de Corazón a Corazón": dict(imagen=B44 + "a7e7e4df0_PHOTO-2026-06-14-23-21-19.jpg"),
}

# ---------- Actividades del sitio (próximas y pasadas; las pasadas dan historial) ----------
# (centro, titulo, categoria, fecha, hora_inicio, hora_fin, lugar, descripcion, requisitos, edad_min, cupos_tot, cupos_ocup, imagen)
ACTIVIDADES = [
    ("Cíclica", "Cíclica: Mega Limpieza", Categoria.medio_ambiente, date(2026, 10, 24), time(8, 0), time(11, 0), "Guadalupe, N.L.",
     "Actividad familiar para ayudar al medio ambiente: limpieza de un área verde y separación de residuos.", ["Guantes", "Gorra y agua"], 5, 40, 12,
     B44 + "b7f757863_ScreenShot2026-10-13at145959.png"),
    ("Familia Misionera", "Familia Misionera Octubre", Categoria.comunidad, date(2026, 10, 24), time(9, 30), time(13, 0),
     "Bahía de La Paz 223, San Gilberto, Santa Catarina", "Misiones en familia por el día: visita a familias de la zona. Este mes el tema es los Santos.",
     ["Ropa cómoda", "Llevar una despensa (opcional)"], 4, 25, 1, B44 + "23d529f42_images.jpg"),
    ("Regalando Estrellas", "Regalando Estrellas: Visita al Materno Infantil", Categoria.ninos, date(2026, 11, 7), time(9, 45), time(12, 0),
     "Av. San Rafael No. 450, Guadalupe", "Entrega de aproximadamente 200 desayunos. Entrega de regalos, juguetes y kits de higiene personal a las familias del hospital.",
     ["Aportación en especie", "Llegar 15 minutos antes"], 6, 10, 7, B44 + "1c9857955_Capturadepantalla2026-05-12alas75712pm.png"),
    ("Familia Misionera", "Familia Misionera Noviembre", Categoria.comunidad, date(2026, 11, 28), time(9, 30), time(13, 0),
     "Bahía de La Paz 223, San Gilberto, Santa Catarina", "Misiones en familia por el día: visita a familias de la zona y convivencia.",
     ["Ropa cómoda"], 4, 25, 0, B44 + "3665a4754_images.jpg"),
    ("Regalando Estrellas", "Posada Sendero", Categoria.comunidad, date(2026, 11, 28), time(9, 30), time(12, 30),
     "San Ildefonso S/N, Col. Sendero, Santa Catarina", "Posada navideña para las familias del Arroyo en la Colonia Sendero: piñatas, aguinaldos y convivencia.",
     ["Aportación en especie", "Llevar aguinaldos"], 3, 15, 9, B44 + "dab0c4d63_Capturadepantalla2026-05-12alas75712pm.png"),
    ("Familia Misionera", "Familia Misionera Posada", Categoria.comunidad, date(2026, 12, 19), time(9, 30), time(13, 0),
     "Bahía de La Paz 223, San Gilberto, Santa Catarina", "Posada de fin de año con las familias de San Gilberto.", ["Ropa cómoda"], 4, 25, 0, B44 + "c7dc5f690_images.jpg"),
    ("Apadrina un Niño", "Servir en el comedor de Apadrina un Niño", Categoria.comunidad, date(2026, 11, 13), time(12, 30), time(15, 0),
     "Cuautla 208, Col. 5 de Mayo, Monterrey", "Apoya a servir y emplatar las 200 comidas que se dan a las familias de la Clínica 25.", ["Cabello recogido", "Zapatos cerrados"], 10, 8, 2,
     B44 + "958716f43_PHOTO-2026-05-07-18-49-24.jpg"),
    ("La Gran Familia", "Tarde de juegos en La Gran Familia", Categoria.ninos, date(2026, 11, 21), time(16, 0), time(18, 30),
     "Carretera Nacional Km 255, Villa de Santiago", "Dinámicas, juegos y manualidades con los niños y adolescentes de la casa hogar. Solo adultos para la visita interna.",
     ["Solo adultos", "Llevar una actividad preparada"], 18, 12, 4, B44 + "8666a1f17_2CD95152-0A8D-445A-BB8E-B7DF7B0C327A.png"),
    # Pasadas (estado finalizada): sirven para el historial de la familia demo
    ("Apadrina un Niño", "Festejo a los papás de Apadrina un Niño", Categoria.ninos, date(2026, 6, 13), time(10, 0), time(13, 0),
     "Cuautla 208, Col. 5 de Mayo, Monterrey", "Celebración del Día del Padre con los papás de los niños del albergue: juegos y convivencia con 5 familias completas.",
     ["Aportación de $500 por familia"], 3, 20, 20, B44 + "958716f43_PHOTO-2026-05-07-18-49-24.jpg"),
    ("Regalando Estrellas", "Regalando Estrellas: Visita al Materno Infantil (julio)", Categoria.ninos, date(2026, 7, 4), time(9, 45), time(12, 0),
     "Av. San Rafael No. 450, Guadalupe", "Entrega de aproximadamente 200 desayunos, regalos, juguetes y kits de higiene personal.", ["Llegar 15 minutos antes"], 6, 20, 20,
     B44 + "1c9857955_Capturadepantalla2026-05-12alas75712pm.png"),
    ("Cíclica", "Mega Limpieza de julio", Categoria.medio_ambiente, date(2026, 7, 4), time(8, 0), time(11, 0), "Guadalupe, N.L.",
     "Actividad familiar para ayudar al medio ambiente.", ["Guantes"], 5, 40, 33, B44 + "a1ec33aea_PHOTO-2026-05-30-14-42-53.jpg"),
    ("Regalando Estrellas", "Regalando Estrellas: Visita al Materno Infantil (agosto)", Categoria.ninos, date(2026, 8, 1), time(9, 45), time(12, 0),
     "Av. San Rafael No. 450, Guadalupe", "Entrega de aproximadamente 200 desayunos, regalos, juguetes y kits de higiene personal.", ["Llegar 15 minutos antes"], 6, 20, 17,
     B44 + "1c9857955_Capturadepantalla2026-05-12alas75712pm.png"),
    ("Regalando Estrellas", "Regalando Estrellas: Visita al Materno Infantil (septiembre)", Categoria.ninos, date(2026, 9, 5), time(9, 45), time(12, 0),
     "Av. San Rafael No. 450, Guadalupe", "Entrega de aproximadamente 200 desayunos, regalos, juguetes y kits de higiene personal.", ["Aportación en especie"], 6, 9, 9,
     B44 + "1c9857955_Capturadepantalla2026-05-12alas75712pm.png"),
    ("Cíclica", "Mega Limpieza San Pedro", Categoria.medio_ambiente, date(2026, 9, 26), time(8, 0), time(11, 0),
     "Humberto Lobo esq. Av. Morones Prieto, San Pedro", "Actividad familiar para ayudar haciendo limpieza al medio ambiente.", ["Guantes", "Gorra y agua"], 5, 40, 28,
     B44 + "a1ec33aea_PHOTO-2026-05-30-14-42-53.jpg"),
    ("Regalando Estrellas", "Regalando Estrellas: Visita al Materno Infantil (octubre)", Categoria.ninos, date(2026, 10, 3), time(9, 45), time(12, 0),
     "Av. San Rafael No. 450, Guadalupe", "Entrega de aproximadamente 200 desayunos, regalos, juguetes y kits de higiene personal.", ["Aportación en especie"], 6, 5, 5,
     B44 + "1c9857955_Capturadepantalla2026-05-12alas75712pm.png"),
    ("Morada del Anciano Desvalido de Cadereyta", "Lotería con los abuelitos de la Morada", Categoria.adultos_mayores, date(2026, 5, 17), time(11, 0), time(13, 0),
     "Blvd. José María González #1000, Cadereyta", "Mañana de lotería, música y plática con los 46 residentes del asilo.", ["Cubrebocas"], 5, 20, 18,
     B44 + "6d3492449_4f610831-7c0a-491a-87af-dad6409e9d8e.png"),
    ("Forma-T", "Cuentacuentos con Forma-T (mayo)", Categoria.ninos, date(2026, 5, 30), time(10, 0), time(12, 0),
     "Col. Independencia, Monterrey", "Lectura de cuentos y manualidad con los niños del programa.", ["Llevar un libro infantil"], 4, 12, 12,
     B44 + "154fb03a1_PHOTO-2026-06-12-14-13-07.jpg"),
    ("Cocinando de Corazón a Corazón", "Empacar alimentos con Cocinando de Corazón", Categoria.comunidad, date(2026, 8, 22), time(16, 0), time(18, 0),
     "Col. Centro, Monterrey", "Preparación y empaque de los alimentos que se distribuyen por la red de parroquias.", ["Cabello recogido"], 10, 15, 15,
     B44 + "a7e7e4df0_PHOTO-2026-06-14-23-21-19.jpg"),
    ("Hogar de la Misericordia", "Tarde de música en Hogar de la Misericordia", Categoria.comunidad, date(2026, 9, 12), time(16, 0), time(18, 0),
     "Calle 20 de Noviembre #200, Santa Catarina", "Convivencia con los residentes: música, juegos de mesa y merienda.", ["Previo aviso", "Máximo 15 personas"], 6, 15, 15,
     B44 + "6b205f6b9_Capturadepantalla2026-05-27alas43501pm.png"),
]

# (centro, titulo, descripcion, que_llevar, donde, horario, dias_hasta, imagen)
CAMPANAS = [
    ("Hogar de la Misericordia", "Pañales y despensa para el Hogar de la Misericordia",
     "Pañales de adulto, alimentos y productos de limpieza para las personas con enfermedades irreversibles que viven en el hogar.",
     ["Pañales de adulto M y G", "Atún, arroz, pasta y frijol", "Jabón líquido y papel sanitario"], "Calle 20 de Noviembre #200, Santa Catarina", "Con previo aviso", 45,
     B44 + "2cad490ba_Capturadepantalla2026-05-27alas43501pm.png"),
    ("La Gran Familia", "Tenis blancos y útiles para La Gran Familia",
     "Tenis blancos, zapato escolar y útiles para los niños, niñas y adolescentes de la casa hogar en Santiago.",
     ["Tenis blancos", "Zapato escolar", "Útiles escolares", "Ropa e higiene"], "Carretera Nacional Km 255, Villa de Santiago", "Con calendario confirmado", 40,
     B44 + "b63074bd7_2CD95152-0A8D-445A-BB8E-B7DF7B0C327A.png"),
    ("Apadrina un Niño", "Despensa y juguetes para Apadrina un Niño",
     "Alimentos, higiene, ropa de cama y juguetes para los niños en tratamiento de cáncer y sus familias.",
     ["Alimentos no perecederos", "Pañales y toallas húmedas", "Ropa de cama individual", "Juguetes"], "Cuautla 208, Col. 5 de Mayo, Monterrey", "Lunes a viernes 13:00–15:00", 50,
     B44 + "ba25d1412_PHOTO-2026-05-07-18-49-24.jpg"),
    ("VIFAC", "Ropa y pañales para mamás de VIFAC",
     "Ropa de bebé, pañales y alimentos para las mujeres embarazadas que viven en la residencia.",
     ["Ropa de bebé", "Pañales", "Alimentos no perecederos"], "Gral. Ignacio Zaragoza 625 Sur, Guadalupe", "Lunes a viernes 10:00–17:00", 35,
     MEDIA + "01cfd5a19_230870A6-5ACE-4EDD-AC42-6D7787130346.png"),
    ("Asistencia y Ropero del Pobre", "Cobijas para los 104 abuelitos del Ropero del Pobre",
     "Con el frío, los 104 adultos mayores de la asociación necesitan cobijas, ropa abrigadora y productos de higiene.",
     ["Cobijas", "Suéteres y calcetines", "Productos de higiene"], "Hidalgo Sur #637, Zona Centro, Saltillo", "Con cita previa", 55,
     B44 + "cbca106e4_PHOTO-2026-09-25-10-14-12.jpg"),
]

# (centro, titulo, causa, objetivo, descripcion, avance, imagen)  — los que ya existen solo reciben foto/descripción
PROYECTOS = [
    ("Trazo", "Trazo… Escribiendo una nueva historia", "Mujeres", "25 mujeres acompañadas",
     "Trazo nace de la Asociación Renace y desde hace más de 2 años lleva pláticas de desarrollo humano y cursos de acuarela y caligrafía a mujeres privadas de la libertad en el Centro de Reinserción Social de Escobedo. Se buscan voluntarias que impartan pláticas o talleres creativos, y donativos para materiales y los alimentos que se entregan en cada visita.", 0.5,
     B44 + "621cf18ba_PHOTO-2026-09-23-13-44-53.jpg"),
    ("DIF San Pedro", "Voluntariado DIF Te Acompaña", "Adultos mayores", "200 adultos mayores acompañados",
     "Acompañar a adultos mayores o jóvenes vulnerables, en soledad, con discapacidad o con una red de apoyo reducida. Realizar visitas en familia mínimo una vez cada 15 días. Inscribe a tu familia para que el voluntariado les asigne a una persona para visitar o acompañar.", 0.35,
     B44 + "6e20d15fd_PHOTO-2026-07-20-14-06-17.jpg"),
    ("Cocinando de Corazón a Corazón", "Cocinando de Corazón a Corazón", "Alimentación", "Red de parroquias con comedor",
     "Desde hace 6 años un conjunto de amas de casa cocina desde su casa para repartir alimentos en comunidades vulnerables a través de una red de parroquias. Puedes cocinar un mínimo de 20 platillos un día fijo a la semana, apoyar al equipo del comedor sirviendo y emplatando, o donar alimentos.", 0.7,
     B44 + "a7e7e4df0_PHOTO-2026-06-14-23-21-19.jpg"),
    ("Forma-T", "Forma-T: formación en valores y apoyo académico", "Educación", "Alumnos de escuelas públicas con rezago",
     "Desde 2016 Forma-T ofrece apoyo académico impartido por voluntarias a alumnos de escuelas públicas con rezago escolar, escuela para padres y formación en valores. Puedes dar sesiones de 45 min en valores una vez por semana, o apoyar a un alumno fijo durante el semestre en lectoescritura o matemáticas.", 0.6,
     B44 + "154fb03a1_PHOTO-2026-06-12-14-13-07.jpg"),
    ("Regalando Estrellas", "Materno Infantil – Regalando Estrellas", "Salud", "1,500 bebés y mamás al año",
     "Desde hace 11 años se visita el Hospital Materno Infantil el primer sábado de cada mes: se regalan 200 desayunos, se visita a los enfermos y se entregan kits de higiene personal a las mamás. Puedes armar kits (toallas húmedas, chanclas, pañales, shampoo, cepillo de dientes, papel y agua) o repartir desayunos.", 0.8,
     B44 + "a5c31e1a6_Capturadepantalla2026-05-12alas75712pm.png"),
    ("Familia Viva", "Bibliotecas Infantiles – Familia Viva", "Educación", "Salitas de lectura en escuelas públicas",
     "Recolección de cuentos infantiles de preescolar, primaria y secundaria para crear bibliotecas que se donan a instituciones con niños. Se reúnen los libros, se consigue un librero y se entrega la salita completa. En 2025 se entregaron 38 salitas de lectura.", 0.76,
     B44 + "1bff8e704_Capturadepantalla2026-05-12alas75105pm.png"),
    ("Regalando Estrellas", "Sendero – Regalando Estrellas", "Mujeres", "Mujeres de la Col. Sendero acompañadas",
     "Pláticas, manualidades y convivencia con mujeres en situación vulnerable de la Colonia Sendero, el último sábado de cada mes de 10:00 a 12:00. Solo mujeres. Hacer una visita en grupo donde puedan enseñar, convivir y compartir aprendizajes.", 0.45,
     B44 + "d649af1d9_Capturadepantalla2026-05-12alas75712pm.png"),
    ("Escucha Corazón", "Escucha Corazón: acompañamiento en Mano Amiga", "Adolescentes", "55 alumnas acompañadas",
     "Una visita al mes al Colegio Mano Amiga Monterrey para dar acompañamiento a alumnas de primaria y secundaria. Mínimo 4 visitas en el ciclo escolar, unos 25 minutos con cada alumna; de 2 a 4 alumnas por voluntaria, con horario y días flexibles. Vigente hasta junio de 2027.", 0.3,
     B44 + "95d3573ab_0.png"),
]

# ---------- Historial de la familia demo ----------
TESTIMONIOS = [
    ("Regalando Estrellas: Visita al Materno Infantil (septiembre)", "Repartir los desayunos con los niños fue de las mejores mañanas que hemos tenido como familia. Las mamás del hospital nos recibieron con una sonrisa enorme."),
    ("Mega Limpieza San Pedro", "Entre todos juntamos 40 bolsas de basura del arroyo. Los niños ahora separan la basura en casa sin que se los pidamos."),
    ("Lotería con los abuelitos de la Morada", "Los abuelitos nos ganaron en la lotería tres veces seguidas. Prometimos volver y ya tenemos fecha."),
]
COMENTARIOS = [
    ("Regalando Estrellas: Visita al Materno Infantil", "¿Se puede llevar fruta además de los desayunos? Vamos con dos niños."),
    ("Cíclica: Mega Limpieza", "Ya nos inscribimos. ¿Hay estacionamiento cerca?"),
    ("Posada Sendero", "El año pasado fue increíble, no se la pierdan."),
    ("Familia Misionera Octubre", "Primera vez que vamos, ¿a qué hora termina más o menos?"),
]
COMENTARIOS_OTRAS = [
    ("familia.ramirez@demo.familiasquesuman.com", "Regalando Estrellas: Visita al Materno Infantil", "Nosotros fuimos en agosto y repetimos este mes. Muy bien organizado."),
    ("familia.ramirez@demo.familiasquesuman.com", "Cíclica: Mega Limpieza", "Lleven gorra, el sol pega fuerte desde las 9."),
    ("familia.lopez@demo.familiasquesuman.com", "Posada Sendero", "¿Aceptan aguinaldos ya armados?"),
]
RESPUESTAS_ANTES = [
    {"expectativa": "Convivir en familia y que los niños vean cómo se ayuda", "animo": 5, "primera_vez": "no"},
    {"expectativa": "Conocer a la asociación y ver si podemos ir seguido", "animo": 4, "primera_vez": "si"},
]
RESPUESTAS_DESPUES = [
    {"experiencia": 5, "aprendizaje": "Que ayudar no requiere mucho tiempo, solo ganas", "repetiria": 5, "recomendaria": "si"},
    {"experiencia": 4, "aprendizaje": "Los niños aprendieron a convivir con los abuelitos", "repetiria": 5, "recomendaria": "si"},
]


def _utc(d: date, h: time) -> datetime:
    return datetime.combine(d, h, tzinfo=timezone.utc)


async def _foto(url: str | None, prefijo: str, cache: dict) -> str | None:
    """Descarga una imagen del sitio y la guarda en MinIO con la misma normalización que las subidas por la app."""
    if not url:
        return None
    if url in cache:
        return cache[url]
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "FamiliasQueSuman-seed/1.0"})
        r.raise_for_status()
        datos = storage.normalizar_imagen(r.content)
        key = storage.nueva_key(prefijo)
        await storage.guardar(key, datos)
        cache[url] = key
        print(f"  foto {prefijo}: {len(datos) // 1024} KB")
        return key
    except Exception as e:  # noqa: BLE001 — una foto que falle no detiene el seed
        print(f"  (sin foto para {prefijo}: {e})")
        cache[url] = None
        return None


async def catalogo(db, fotos: bool) -> dict[str, Centro]:
    ciudades = {c.clave: c for c in (await db.execute(select(Ciudad))).scalars()}
    centros = {c.nombre: c for c in (await db.execute(select(Centro))).scalars()}
    cache: dict = {}

    def buscar(nombre: str) -> Centro | None:
        return centros.get(nombre)

    print("Centros…")
    for nombre, d in CENTROS.items():
        c = buscar(nombre)
        if c is None and "tipo" not in d:
            print(f"  falta en la base (corre scripts.seed primero): {nombre}")
            continue
        if c is None:
            c = Centro(nombre=nombre, verificado=True, ciudad_id=ciudades[d.get("ciudad", "monterrey")].id,
                       correo=f"contacto@{nombre.split()[0].lower()}.org.mx", tipo="", categoria=Categoria.comunidad, descripcion="", direccion="")
            db.add(c)
            centros[nombre] = c
            print(f"  nuevo: {nombre}")
        for k in ("tipo", "categoria", "descripcion", "direccion", "horario_visitas", "que_necesitan", "acepta", "telefono", "whatsapp"):
            if k in d:
                setattr(c, k, d[k])
        if fotos and not c.imagen_key:
            c.imagen_key = await _foto(d.get("imagen"), "centros", cache)
    await db.flush()

    print("Actividades…")
    existentes = {a.titulo.lower() for a in (await db.execute(select(Actividad))).scalars()}
    for (cn, tit, cat, fecha, hi, hf, lugar, desc, req, edad, tot, ocu, img) in ACTIVIDADES:
        if tit.lower() in existentes:
            continue
        c = buscar(cn)
        a = Actividad(centro_id=c.id, ciudad_id=c.ciudad_id, titulo=tit, categoria=cat, fecha=fecha, hora_inicio=hi, hora_fin=hf, lugar=lugar,
                      descripcion=desc, requisitos=req, edad_minima=edad, apta_ninos=edad < 18, cupos_totales=tot, cupos_ocupados=ocu,
                      estado=EstadoActividad.finalizada if fecha < HOY else EstadoActividad.activa)
        if fotos:
            a.imagen_key = await _foto(img, "actividades", cache)
        db.add(a)
    await db.flush()

    print("Campañas…")
    existentes = {k.titulo for k in (await db.execute(select(Campana))).scalars()}
    for (cn, tit, desc, llevar, donde, hor, dias, img) in CAMPANAS:
        if tit in existentes:
            continue
        c = buscar(cn)
        k = Campana(centro_id=c.id, ciudad_id=c.ciudad_id, titulo=tit, descripcion=desc, que_llevar=llevar, donde_entregar=donde,
                    horario_entrega=hor, hasta=HOY + timedelta(days=dias))
        if fotos:
            k.imagen_key = await _foto(img, "campanas", cache)
        db.add(k)
    # Fotos para las campañas que ya existían (la de su centro)
    if fotos:
        for k in (await db.execute(select(Campana).where(Campana.imagen_key.is_(None)))).scalars():
            centro = await db.get(Centro, k.centro_id)
            url = CENTROS.get(centro.nombre, {}).get("imagen") if centro else None
            k.imagen_key = await _foto(url, "campanas", cache)
    await db.flush()

    print("Proyectos…")
    existentes = {p.titulo.split("…")[0].split("–")[0].strip().lower(): p for p in (await db.execute(select(Proyecto))).scalars()}
    for (cn, tit, causa, obj, desc, av, img) in PROYECTOS:
        clave = tit.split("…")[0].split("–")[0].strip().lower()
        p = existentes.get(clave)
        if p is None:
            c = buscar(cn)
            p = Proyecto(centro_id=c.id, titulo=tit, causa=causa, objetivo=obj, descripcion=desc, avance=av)
            db.add(p)
        else:
            p.titulo, p.causa, p.objetivo, p.descripcion, p.avance = tit, causa, obj, desc, av
        if fotos and not p.imagen_key:
            p.imagen_key = await _foto(img, "proyectos", cache)
    await db.flush()
    # Actividades viejas del seed sin foto: la de su centro
    if fotos:
        for a in (await db.execute(select(Actividad).where(Actividad.imagen_key.is_(None)))).scalars():
            centro = await db.get(Centro, a.centro_id)
            url = CENTROS.get(centro.nombre, {}).get("imagen") if centro else None
            a.imagen_key = await _foto(url, "actividades", cache)
    await db.flush()
    return centros


async def historial(db, correo: str, fotos: bool) -> None:
    u = await db.scalar(select(Usuario).where(Usuario.email == correo.lower()))
    fam = await db.scalar(select(Familia).options(selectinload(Familia.integrantes)).where(Familia.usuario_id == u.id)) if u else None
    if u is None or fam is None:
        print(f"No existe una familia con el correo {correo}; crea la cuenta en la app primero.")
        return
    integrantes = list(fam.integrantes)
    if not integrantes:
        print("La familia no tiene integrantes; agrega al menos uno en la app.")
        return
    actividades = {a.titulo: a for a in (await db.execute(select(Actividad))).scalars()}
    pasadas = sorted([a for a in actividades.values() if a.fecha < HOY], key=lambda a: a.fecha)
    ya = {i.actividad_id for i in (await db.execute(select(Inscripcion).where(Inscripcion.familia_id == fam.id))).scalars()}
    rnd = random.Random(42)
    cache: dict = {}

    print(f"Historial para {fam.nombre} ({correo})…")
    nuevas = 0
    for n, a in enumerate(pasadas):
        if a.id in ya:
            continue
        quienes = integrantes[: max(1, min(len(integrantes), 2 + n % 2))]
        ins = Inscripcion(actividad_id=a.id, familia_id=fam.id, personas=len(quienes), estado=EstadoInscripcion.asistio,
                          comentario="Vamos en familia" if n % 3 == 0 else None)
        ins.asistentes = [Asistente(integrante_id=i.id, nombre=i.nombre, edad=i.edad) for i in quienes]
        db.add(ins)
        await db.flush()
        db.add(EncuestaRespuesta(inscripcion_id=ins.id, momento=Momento.antes, respuestas=RESPUESTAS_ANTES[n % 2], creado_en=_utc(a.fecha - timedelta(days=2), time(20, 0))))
        db.add(EncuestaRespuesta(inscripcion_id=ins.id, momento=Momento.despues, respuestas=RESPUESTAS_DESPUES[n % 2], creado_en=_utc(a.fecha, time(19, 0))))
        nuevas += 1
    print(f"  {nuevas} actividades completadas (total {len(pasadas)})")

    # Testimonios aprobados con foto
    tiene = {t.actividad_id for t in (await db.execute(select(Testimonio).where(Testimonio.familia_id == fam.id))).scalars()}
    for tit, texto in TESTIMONIOS:
        a = actividades.get(tit)
        if a is None or a.id in tiene:
            continue
        t = Testimonio(familia_id=fam.id, actividad_id=a.id, texto=texto, estado=EstadoModeracion.aprobado, moderado_en=_utc(a.fecha + timedelta(days=2), time(10, 0)))
        if fotos and a.imagen_key:
            datos = await storage.leer(a.imagen_key)
            if datos:
                t.foto_key = storage.nueva_key("testimonios")
                await storage.guardar(t.foto_key, datos)
        db.add(t)

    # Comentarios aprobados (de esta familia y de otras demo) y likes
    async def comentar(usuario_id, tipo, objetivo_id, texto):
        existe = await db.scalar(select(Comentario.id).where(Comentario.usuario_id == usuario_id, Comentario.objetivo_id == objetivo_id))
        if not existe:
            db.add(Comentario(usuario_id=usuario_id, objetivo_tipo=tipo, objetivo_id=objetivo_id, texto=texto, estado=EstadoModeracion.aprobado))

    for tit, texto in COMENTARIOS:
        a = actividades.get(tit)
        if a:
            await comentar(u.id, TipoObjetivo.actividad, a.id, texto)
    for correo_otra, tit, texto in COMENTARIOS_OTRAS:
        otra = await db.scalar(select(Usuario).where(Usuario.email == correo_otra))
        a = actividades.get(tit)
        if otra and a:
            await comentar(otra.id, TipoObjetivo.actividad, a.id, texto)

    otras = list((await db.execute(select(Usuario).where(Usuario.email.like("%@demo.familiasquesuman.com")))).scalars())
    objetivos = [(TipoObjetivo.actividad, a.id) for a in actividades.values() if a.fecha >= HOY]
    objetivos += [(TipoObjetivo.campana, k.id) for k in (await db.execute(select(Campana))).scalars()]
    objetivos += [(TipoObjetivo.proyecto, p.id) for p in (await db.execute(select(Proyecto))).scalars()]
    likes_actuales = {(l.usuario_id, l.objetivo_tipo, l.objetivo_id) for l in (await db.execute(select(Like))).scalars()}
    for tipo, oid in objetivos:
        for quien in [u] + otras:
            if (quien.id, tipo, oid) in likes_actuales:
                continue
            r = random.Random(f"{quien.id}:{oid}")  # decisión fija por (usuario, objetivo): volver a correr no agrega likes
            if quien.id == u.id or r.random() < 0.5:
                db.add(Like(usuario_id=quien.id, objetivo_tipo=tipo, objetivo_id=oid, creado_en=datetime.now(timezone.utc) - timedelta(days=r.randint(1, 30))))
                likes_actuales.add((quien.id, tipo, oid))

    # Donaciones registradas
    if not await db.scalar(select(Donacion.id).where(Donacion.familia_id == fam.id)):
        campanas = list((await db.execute(select(Campana).order_by(Campana.hasta))).scalars())
        for k, (tipo, detalle) in zip(campanas[:2], [("alimentos", "2 bolsas de arroz y 4 de frijol"), ("higiene", "Paquete de pañales y jabón")]):
            db.add(Donacion(familia_id=fam.id, centro_id=k.centro_id, campana_id=k.id, tipo=tipo, detalle=detalle,
                            creado_en=datetime.now(timezone.utc) - timedelta(days=rnd.randint(3, 20))))

    # Notificaciones (2 sin leer)
    if not await db.scalar(select(Notificacion.id).where(Notificacion.usuario_id == u.id)):
        prox = min((a for a in actividades.values() if a.fecha >= HOY), key=lambda a: a.fecha, default=None)
        avisos = [
            ("¡Nueva insignia!", "Tu familia desbloqueó «Familia que Suma» por 10 actividades completadas.", "insignia", None, True),
            ("Testimonio publicado", "Tu testimonio sobre la Mega Limpieza ya se ve en Nuestras familias.", "testimonio", None, True),
            ("Recordatorio", f"Mañana: {prox.titulo if prox else 'tu próxima actividad'}. ¡Los esperamos!", "recordatorio", prox.id if prox else None, False),
            ("Gracias por tu donación", "El centro recibió tu aportación a la campaña. ¡Gracias por sumar!", "donacion", None, False),
        ]
        for i, (tit, cuerpo, tipo, ref, leida) in enumerate(avisos):
            db.add(Notificacion(usuario_id=u.id, titulo=tit, cuerpo=cuerpo, tipo=tipo, referencia_id=ref, leida=leida,
                                creado_en=datetime.now(timezone.utc) - timedelta(days=len(avisos) - i, hours=3)))
    await db.flush()
    print("  testimonios, comentarios, likes, donaciones y notificaciones listos")


async def main(familia: str | None, fotos: bool) -> None:
    async with SessionLocal() as db:
        if not await db.scalar(select(func.count(Ciudad.id))):
            print("La base está vacía: corre primero  python -m scripts.seed --demo")
            return
        if fotos:
            try:
                storage.asegurar_bucket()
            except Exception as e:  # noqa: BLE001
                print(f"Sin almacenamiento de fotos ({e}); se continúa sin imágenes")
                fotos = False
        await catalogo(db, fotos)
        if familia:
            await historial(db, familia, fotos)
        await db.commit()
        print("Listo.")
    await engine.dispose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--familia", help="correo de la familia que recibirá el historial de demo")
    p.add_argument("--sin-fotos", action="store_true", help="no descargar imágenes del sitio")
    args = p.parse_args()
    asyncio.run(main(args.familia, not args.sin_fotos))

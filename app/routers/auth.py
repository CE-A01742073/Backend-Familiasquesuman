"""Autenticación: registro, login email/contraseña, Google, refresh con rotación, logout."""
import asyncio
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import auditar
from app.core.config import get_settings
from app.core.deps import DB, UsuarioActual
from app.core.metrics import LOGINS_FALLIDOS, LOGINS_OK, REGISTROS
from app.core.ratelimit import ip_cliente, limite_auth
from app.core.security import (
    crear_access_token,
    generar_refresh_token,
    hash_password,
    hash_refresh,
    password_valida,
    verify_password,
)
from app.db.base import ahora
from app.models.catalogo import Ciudad
from app.models.usuarios import Familia, RefreshToken, Rol, Usuario
from app.schemas.auth import CambiarPasswordIn, GoogleIn, LoginIn, RefreshIn, RegistroIn, TokensOut, UsuarioOut
from app.schemas.comunes import Mensaje
from app.services.comunes import url_imagen

log = logging.getLogger("familias.auth")
router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(limite_auth)])

CREDENCIALES_INCORRECTAS = "Correo o contraseña incorrectos"


def usuario_out(u: Usuario) -> UsuarioOut:
    return UsuarioOut(
        id=u.id,
        email=u.email,
        nombre=u.nombre,
        rol=u.rol,
        descripcion=u.descripcion,
        tiene_foto=u.foto_key is not None,
        foto_url=url_imagen(u.foto_key),
        centro_id=u.centro_id,
        tiene_password=u.password_hash is not None,
        tiene_google=u.google_sub is not None,
    )


async def _emitir_tokens(db: AsyncSession, u: Usuario, request: Request, familia_creada: bool = False) -> TokensOut:
    s = get_settings()
    access, expira = crear_access_token(u.id, u.rol.value)
    claro, hashed = generar_refresh_token()
    db.add(
        RefreshToken(
            usuario_id=u.id,
            token_hash=hashed,
            expira_en=ahora() + timedelta(days=s.REFRESH_TOKEN_DAYS),
            creado_en=ahora(),
            user_agent=(request.headers.get("user-agent") or "")[:200],
        )
    )
    return TokensOut(access_token=access, refresh_token=claro, expires_in=expira, usuario=usuario_out(u), familia_creada=familia_creada)


async def _ciudad(db: AsyncSession, clave: str) -> Ciudad:
    c = await db.scalar(select(Ciudad).where(Ciudad.clave == clave.lower(), Ciudad.activa.is_(True)))
    if c is None:
        raise HTTPException(422, "Ciudad no disponible")
    return c


@router.post("/registro", response_model=TokensOut, status_code=201)
async def registro(datos: RegistroIn, request: Request, db: DB):
    """RF-16: crear cuenta con correo y contraseña. Crea también la familia."""
    if not datos.acepta_aviso_privacidad:
        raise HTTPException(422, "Debes aceptar el aviso de privacidad")
    if (err := password_valida(datos.password)) is not None:
        raise HTTPException(422, err)
    ciudad = await _ciudad(db, datos.ciudad)
    email = datos.email.lower()

    existente = await db.scalar(select(Usuario).where(Usuario.email == email))
    if existente is not None:
        # Mismo mensaje que un alta exitosa NO; pero tampoco se revela el correo a terceros:
        # el límite por IP evita enumeración masiva, y la respuesta es genérica.
        await auditar(db, "registro_duplicado", ip=ip_cliente(request), exito=False)
        await db.commit()
        raise HTTPException(409, "No se pudo crear la cuenta con esos datos")

    u = Usuario(email=email, password_hash=await asyncio.to_thread(hash_password, datos.password), nombre=datos.nombre, rol=Rol.familia)
    u.familia = Familia(nombre=datos.nombre_familia, ciudad_id=ciudad.id)
    db.add(u)
    await db.flush()
    await auditar(db, "registro", usuario_id=u.id, ip=ip_cliente(request))
    REGISTROS.labels(metodo="password").inc()
    return await _emitir_tokens(db, u, request, familia_creada=True)


@router.post("/login", response_model=TokensOut)
async def login(datos: LoginIn, request: Request, db: DB):
    """RF-17. Bloqueo progresivo por cuenta tras LOGIN_MAX_FAILS intentos (A07)."""
    s = get_settings()
    ip = ip_cliente(request)
    email = datos.email.lower()
    u = await db.scalar(select(Usuario).where(Usuario.email == email))

    if u is not None and u.bloqueado_hasta and u.bloqueado_hasta > ahora():
        await auditar(db, "login_bloqueado", usuario_id=u.id, ip=ip, exito=False)
        LOGINS_FALLIDOS.labels(motivo="bloqueado").inc()
        await db.commit()  # la auditoría debe persistir aunque la respuesta sea de error
        raise HTTPException(
            status.HTTP_423_LOCKED,
            f"Cuenta bloqueada temporalmente por intentos fallidos. Intenta en {s.LOGIN_LOCK_MINUTES} minutos.",
        )

    ok = await asyncio.to_thread(verify_password, datos.password, u.password_hash if u else None)
    if u is None or not ok or not u.activo or u.eliminado_en is not None:
        if u is not None:
            u.intentos_fallidos += 1
            if u.intentos_fallidos >= s.LOGIN_MAX_FAILS:
                u.bloqueado_hasta = ahora() + timedelta(minutes=s.LOGIN_LOCK_MINUTES)
                u.intentos_fallidos = 0
                await auditar(db, "cuenta_bloqueada", usuario_id=u.id, ip=ip, exito=False)
        await auditar(db, "login_fallido", usuario_id=u.id if u else None, ip=ip, exito=False)
        LOGINS_FALLIDOS.labels(motivo="credenciales").inc()
        await db.commit()  # el contador de intentos y la auditoría se guardan aunque se responda 401
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, CREDENCIALES_INCORRECTAS)

    u.intentos_fallidos = 0
    u.bloqueado_hasta = None
    await auditar(db, "login", usuario_id=u.id, ip=ip)
    LOGINS_OK.labels(metodo="password").inc()
    return await _emitir_tokens(db, u, request)


async def _verificar_google(id_token_str: str) -> dict:
    """Verifica firma, expiración y audiencia del ID token contra las llaves públicas de Google."""
    from google.auth.transport import requests as grequests
    from google.oauth2 import id_token

    s = get_settings()
    if not s.google_client_ids:
        raise HTTPException(503, "Inicio de sesión con Google no está configurado")

    def _v():
        info = id_token.verify_oauth2_token(id_token_str, grequests.Request())
        if info.get("aud") not in s.google_client_ids:
            raise ValueError("aud")
        if info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            raise ValueError("iss")
        if not info.get("email_verified"):
            raise ValueError("email_verified")
        return info

    try:
        return await asyncio.to_thread(_v)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token de Google inválido")


@router.post("/google", response_model=TokensOut)
async def login_google(datos: GoogleIn, request: Request, db: DB):
    """Google Sign-In: el servidor verifica el ID token y emite SU PROPIO JWT."""
    info = await _verificar_google(datos.id_token)
    sub, email = str(info["sub"]), str(info["email"]).lower()
    ip = ip_cliente(request)
    familia_creada = False

    u = await db.scalar(select(Usuario).where(Usuario.google_sub == sub))
    if u is None:
        # Vincular con cuenta existente del mismo correo verificado, o crear una nueva.
        u = await db.scalar(select(Usuario).where(Usuario.email == email))
        if u is None:
            if not datos.acepta_aviso_privacidad:
                raise HTTPException(422, "Debes aceptar el aviso de privacidad")
            if not datos.nombre_familia or not datos.ciudad:
                raise HTTPException(422, "Falta nombre de la familia o ciudad")
            ciudad = await _ciudad(db, datos.ciudad)
            u = Usuario(email=email, google_sub=sub, nombre=str(info.get("name") or email.split("@")[0])[:80], rol=Rol.familia)
            u.familia = Familia(nombre=datos.nombre_familia, ciudad_id=ciudad.id)
            db.add(u)
            await db.flush()
            familia_creada = True
            REGISTROS.labels(metodo="google").inc()
            await auditar(db, "registro_google", usuario_id=u.id, ip=ip)
        else:
            u.google_sub = sub
            await auditar(db, "google_vinculado", usuario_id=u.id, ip=ip)

    if not u.activo or u.eliminado_en is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Cuenta no disponible")
    await auditar(db, "login", usuario_id=u.id, ip=ip, detalle="google")
    LOGINS_OK.labels(metodo="google").inc()
    return await _emitir_tokens(db, u, request, familia_creada)


@router.post("/refresh", response_model=TokensOut)
async def refresh(datos: RefreshIn, request: Request, db: DB):
    """Rotación: cada refresh token se usa UNA vez. Reuso de uno revocado → se revocan todos (robo detectado)."""
    h = hash_refresh(datos.refresh_token)
    rt = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == h))
    if rt is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida")
    if rt.revocado:
        await db.execute(update(RefreshToken).where(RefreshToken.usuario_id == rt.usuario_id).values(revocado=True))
        await auditar(db, "refresh_reusado", usuario_id=rt.usuario_id, ip=ip_cliente(request), exito=False)
        await db.commit()  # la revocación masiva debe persistir
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión inválida")
    if rt.expira_en < ahora():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión expirada")

    u = await db.get(Usuario, rt.usuario_id)
    if u is None or not u.activo or u.eliminado_en is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Cuenta no disponible")

    rt.revocado = True
    tokens = await _emitir_tokens(db, u, request)
    await db.flush()
    nuevo = await db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh(tokens.refresh_token)))
    rt.reemplazado_por = nuevo.id if nuevo else None
    return tokens


@router.post("/logout", response_model=Mensaje)
async def logout(datos: RefreshIn, usuario: UsuarioActual, request: Request, db: DB):
    h = hash_refresh(datos.refresh_token)
    await db.execute(
        update(RefreshToken).where(RefreshToken.token_hash == h, RefreshToken.usuario_id == usuario.id).values(revocado=True)
    )
    await auditar(db, "logout", usuario_id=usuario.id, ip=ip_cliente(request))
    return Mensaje(mensaje="Sesión cerrada")


@router.post("/logout-todo", response_model=Mensaje)
async def logout_todo(usuario: UsuarioActual, request: Request, db: DB):
    await db.execute(update(RefreshToken).where(RefreshToken.usuario_id == usuario.id).values(revocado=True))
    await auditar(db, "logout_todo", usuario_id=usuario.id, ip=ip_cliente(request))
    return Mensaje(mensaje="Todas las sesiones fueron cerradas")


@router.post("/cambiar-password", response_model=Mensaje)
async def cambiar_password(datos: CambiarPasswordIn, usuario: UsuarioActual, request: Request, db: DB):
    if not await asyncio.to_thread(verify_password, datos.password_actual, usuario.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "La contraseña actual no es correcta")
    if (err := password_valida(datos.password_nueva)) is not None:
        raise HTTPException(422, err)
    usuario.password_hash = await asyncio.to_thread(hash_password, datos.password_nueva)
    await db.execute(update(RefreshToken).where(RefreshToken.usuario_id == usuario.id).values(revocado=True))
    await auditar(db, "password_cambiada", usuario_id=usuario.id, ip=ip_cliente(request))
    return Mensaje(mensaje="Contraseña actualizada; vuelve a iniciar sesión en tus otros dispositivos")

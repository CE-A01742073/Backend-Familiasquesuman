"""Contraseñas (argon2id) y JWT (HS256 fijo, emitido y verificado solo por esta API)."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

# Parámetros OWASP recomendados para argon2id (m=64 MiB, t=3, p=4)
_ph = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)


def hash_password(password: str) -> str:
    return _ph.hash(password)


_DUMMY_HASH = _ph.hash("dummy-password-para-tiempos-constantes")


def verify_password(password: str, password_hash: str | None) -> bool:
    # Si la cuenta no existe o no tiene contraseña, igual se calcula un hash para que el
    # tiempo de respuesta no revele si el correo está registrado (enumeración de usuarios).
    objetivo = password_hash or _DUMMY_HASH
    try:
        ok = _ph.verify(objetivo, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    return ok and password_hash is not None


def password_valida(password: str) -> str | None:
    """Regresa un mensaje de error o None. Política NIST: longitud, sin reglas de composición absurdas."""
    s = get_settings()
    if len(password) < s.PASSWORD_MIN_LENGTH:
        return f"La contraseña debe tener al menos {s.PASSWORD_MIN_LENGTH} caracteres"
    if len(password) > 128:
        return "La contraseña es demasiado larga"
    if password.lower() in _COMUNES or password.isdigit():
        return "Esa contraseña es demasiado común"
    return None


_COMUNES = {
    "123456789012", "contraseña123", "password1234", "qwertyuiop12", "familiasquesuman",
    "123456789abc", "abcdefghijkl", "monterrey2026", "hermosillo2026",
}


# ---------------- JWT ----------------

def crear_access_token(usuario_id: uuid.UUID, rol: str) -> tuple[str, int]:
    s = get_settings()
    ahora = datetime.now(timezone.utc)
    exp = ahora + timedelta(minutes=s.ACCESS_TOKEN_MINUTES)
    claims = {
        "sub": str(usuario_id),
        "rol": rol,
        "type": "access",
        "jti": secrets.token_hex(16),
        "iat": ahora,
        "nbf": ahora,
        "exp": exp,
        "iss": s.JWT_ISSUER,
        "aud": s.JWT_AUDIENCE,
    }
    token = jwt.encode(claims, s.JWT_SECRET, algorithm=s.JWT_ALGORITHM)
    return token, s.ACCESS_TOKEN_MINUTES * 60


def decodificar_access_token(token: str) -> dict:
    """Lanza jwt.PyJWTError si es inválido. Algoritmo fijado: rechaza 'none' y cambio de alg (A07)."""
    s = get_settings()
    claims = jwt.decode(
        token,
        s.JWT_SECRET,
        algorithms=[s.JWT_ALGORITHM],
        issuer=s.JWT_ISSUER,
        audience=s.JWT_AUDIENCE,
        options={"require": ["exp", "iat", "sub", "jti", "iss", "aud"]},
        leeway=5,
    )
    if claims.get("type") != "access":
        raise jwt.InvalidTokenError("tipo de token incorrecto")
    return claims


def generar_refresh_token() -> tuple[str, str]:
    """Regresa (token en claro para el cliente, sha256 para la BD)."""
    token = secrets.token_urlsafe(48)
    return token, hash_refresh(token)


def hash_refresh(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

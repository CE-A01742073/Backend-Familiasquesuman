import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models.usuarios import Rol
from app.schemas.comunes import Esquema


class RegistroIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    nombre: str = Field(min_length=2, max_length=80)  # nombre de la persona
    nombre_familia: str = Field(min_length=2, max_length=40)
    ciudad: str = Field(min_length=2, max_length=20)  # clave: monterrey | hermosillo
    acepta_aviso_privacidad: bool


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class GoogleIn(BaseModel):
    id_token: str = Field(min_length=20, max_length=4096)
    # Solo se usan si es la primera vez (crear familia):
    nombre_familia: str | None = Field(None, min_length=2, max_length=40)
    ciudad: str | None = Field(None, min_length=2, max_length=20)
    acepta_aviso_privacidad: bool = False


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)


class CambiarPasswordIn(BaseModel):
    password_actual: str = Field(min_length=1, max_length=128)
    password_nueva: str = Field(min_length=1, max_length=128)


class UsuarioOut(Esquema):
    id: uuid.UUID
    email: str
    nombre: str
    rol: Rol
    descripcion: str | None
    tiene_foto: bool = False
    foto_url: str | None = None
    centro_id: uuid.UUID | None = None
    tiene_password: bool = False
    tiene_google: bool = False


class TokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    usuario: UsuarioOut
    familia_creada: bool = False

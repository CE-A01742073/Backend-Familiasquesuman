"""Configuración central. Todo viene de variables de entorno (.env)."""
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Entorno
    ENV: Literal["dev", "test", "prod"] = "dev"
    APP_NAME: str = "Familias que Suman API"
    API_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    # Base de datos
    DATABASE_URL: str = "postgresql+asyncpg://familias:familias@db:5432/familias"

    # JWT (pure JWT emitido por esta API)
    JWT_SECRET: str = Field(min_length=32)
    JWT_ALGORITHM: Literal["HS256"] = "HS256"
    JWT_ISSUER: str = "familiasquesuman-api"
    JWT_AUDIENCE: str = "familiasquesuman-app"
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 30

    # Google Sign-In (ID token verificado en servidor)
    GOOGLE_CLIENT_IDS: str = ""  # separados por coma: web client id, android client id

    # Contraseñas / bloqueo (A07)
    PASSWORD_MIN_LENGTH: int = 12
    LOGIN_MAX_FAILS: int = 5
    LOGIN_LOCK_MINUTES: int = 15

    # Rate limiting por IP (ventana fija). Redis es opcional.
    REDIS_URL: str | None = None
    RATE_LIMIT_AUTH_PER_MINUTE: int = 10
    RATE_LIMIT_GENERAL_PER_MINUTE: int = 120
    RATE_LIMIT_WRITE_PER_MINUTE: int = 30
    TRUST_PROXY_HEADERS: bool = True  # detrás de Cloudflare Tunnel
    RATE_LIMIT_EXEMPT_IPS: str = ""  # separadas por coma; solo para el escáner ZAP durante la auditoría

    # CORS: la app Android no lo necesita; solo para panel web si existe.
    CORS_ORIGINS: str = ""

    # Almacenamiento S3 / MinIO
    S3_ENDPOINT_URL: str = "http://minio:9000"
    S3_ACCESS_KEY: str = "minio"
    S3_SECRET_KEY: str = "miniominio"
    S3_BUCKET: str = "familias"
    S3_REGION: str = "us-east-1"
    MAX_UPLOAD_MB: int = 5

    # Observabilidad
    METRICS_TOKEN: str | None = None  # Prometheus manda Authorization: Bearer <token>

    # Limites generales
    MAX_BODY_BYTES: int = 6 * 1024 * 1024

    @field_validator("JWT_SECRET")
    @classmethod
    def _secreto_fuerte(cls, v: str) -> str:
        debiles = ("changeme", "cambiame", "password", "contrasena", "example", "ejemplo")
        if any(d in v.lower() for d in debiles) or len(set(v)) < 10:
            raise ValueError("JWT_SECRET demasiado débil; genera uno con: openssl rand -hex 48")
        return v

    @property
    def google_client_ids(self) -> list[str]:
        return [c.strip() for c in self.GOOGLE_CLIENT_IDS.split(",") if c.strip()]

    @property
    def rate_limit_exempt_ips(self) -> set[str]:
        return {c.strip() for c in self.RATE_LIMIT_EXEMPT_IPS.split(",") if c.strip()}

    @property
    def cors_origins(self) -> list[str]:
        return [c.strip() for c in self.CORS_ORIGINS.split(",") if c.strip()]

    @property
    def es_prod(self) -> bool:
        return self.ENV == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
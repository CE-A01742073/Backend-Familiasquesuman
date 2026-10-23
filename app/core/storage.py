"""Almacenamiento de imágenes en S3/MinIO. Las imágenes se re-codifican con Pillow:
elimina EXIF/GPS y cualquier payload escondido (A08), y garantiza que sea una imagen real."""
import asyncio
import io
import uuid
from functools import lru_cache

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings

TIPOS_PERMITIDOS = {"image/jpeg", "image/png", "image/webp"}
MAGIA = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",  # RIFF....WEBP
}


class ImagenInvalida(ValueError):
    pass


def detectar_tipo(datos: bytes) -> str | None:
    for firma, tipo in MAGIA.items():
        if datos.startswith(firma):
            if tipo == "image/webp" and datos[8:12] != b"WEBP":
                return None
            return tipo
    return None


def normalizar_imagen(datos: bytes, max_lado: int = 1600) -> bytes:
    """Valida por bytes mágicos + decodificación real, redimensiona y re-codifica a JPEG sin metadatos."""
    if detectar_tipo(datos) is None:
        raise ImagenInvalida("El archivo no es una imagen JPEG, PNG o WebP")
    try:
        with Image.open(io.BytesIO(datos)) as img:
            img.verify()
        with Image.open(io.BytesIO(datos)) as img:
            img = img.convert("RGB")
            img.thumbnail((max_lado, max_lado))
            salida = io.BytesIO()
            img.save(salida, format="JPEG", quality=85, optimize=True)  # sin exif= → se descartan metadatos
            return salida.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise ImagenInvalida("No se pudo procesar la imagen") from e


@lru_cache
def _cliente():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.S3_ENDPOINT_URL,
        aws_access_key_id=s.S3_ACCESS_KEY,
        aws_secret_access_key=s.S3_SECRET_KEY,
        region_name=s.S3_REGION,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=3,
            read_timeout=15,
            retries={"max_attempts": 2},
        ),
    )


def asegurar_bucket() -> None:
    s = get_settings()
    c = _cliente()
    try:
        c.head_bucket(Bucket=s.S3_BUCKET)
    except ClientError:
        c.create_bucket(Bucket=s.S3_BUCKET)


def nueva_key(prefijo: str) -> str:
    return f"{prefijo}/{uuid.uuid4().hex}.jpg"


async def guardar(key: str, datos: bytes) -> None:
    s = get_settings()

    def _put():
        try:
            _cliente().put_object(Bucket=s.S3_BUCKET, Key=key, Body=datos, ContentType="image/jpeg")
        except ClientError as e:
            # Si el almacenamiento arrancó después que la API, el bucket aún no existe: se crea y se reintenta.
            if e.response.get("Error", {}).get("Code") not in ("NoSuchBucket", "404"):
                raise
            asegurar_bucket()
            _cliente().put_object(Bucket=s.S3_BUCKET, Key=key, Body=datos, ContentType="image/jpeg")

    await asyncio.to_thread(_put)


async def leer(key: str) -> bytes | None:
    s = get_settings()

    def _get():
        try:
            return _cliente().get_object(Bucket=s.S3_BUCKET, Key=key)["Body"].read()
        except ClientError:
            return None

    return await asyncio.to_thread(_get)


async def borrar(key: str) -> None:
    s = get_settings()

    def _del():
        try:
            _cliente().delete_object(Bucket=s.S3_BUCKET, Key=key)
        except ClientError:
            pass

    await asyncio.to_thread(_del)

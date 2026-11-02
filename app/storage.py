import io
import uuid

from minio import Minio

from .config import (
    MINIO_ACCESS_KEY, MINIO_BUCKET, MINIO_ENDPOINT, MINIO_SECRET_KEY, MINIO_SECURE,
)

_client = None


def client() -> Minio | None:
    global _client
    if not MINIO_ENDPOINT:
        return None
    if _client is None:
        _client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE,
        )
        if not _client.bucket_exists(MINIO_BUCKET):
            _client.make_bucket(MINIO_BUCKET)
    return _client


def put(data: bytes, filename: str, content_type: str = "application/octet-stream") -> str:
    c = client()
    if c is None:
        return ""
    obj = f"{uuid.uuid4().hex}_{filename}"
    c.put_object(MINIO_BUCKET, obj, io.BytesIO(data), len(data), content_type=content_type)
    scheme = "https" if MINIO_SECURE else "http"
    return f"{scheme}://{MINIO_ENDPOINT}/{MINIO_BUCKET}/{obj}"

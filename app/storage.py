"""私有MinIO对象；API只返回稳定对象引用，下载时短期签名。"""
import io
import uuid
from datetime import timedelta
from pathlib import PurePath
from minio import Minio
from urllib3 import PoolManager, Timeout
from . import config

_client = None


def client():
    global _client
    if not config.MINIO_ENDPOINT:
        raise RuntimeError('未配置对象存储，不能保存截图；请配置MINIO_*')
    if _client is None:
        _client = Minio(config.MINIO_ENDPOINT, access_key=config.MINIO_ACCESS_KEY,
                        secret_key=config.MINIO_SECRET_KEY, secure=config.MINIO_SECURE,
                        http_client=PoolManager(timeout=Timeout(connect=5, read=20), retries=False))
        if not _client.bucket_exists(config.MINIO_BUCKET):
            _client.make_bucket(config.MINIO_BUCKET)
    return _client


def put(data, filename, content_type='application/octet-stream'):
    suffix = PurePath(filename.replace('\\', '/')).suffix[:12]
    obj = f'uploads/{uuid.uuid4().hex}{suffix}'
    client().put_object(config.MINIO_BUCKET, obj, io.BytesIO(data), len(data), content_type=content_type)
    return f's3://{config.MINIO_BUCKET}/{obj}'


def object_name(ref):
    prefix = f's3://{config.MINIO_BUCKET}/'
    if not ref.startswith(prefix):
        raise ValueError('对象引用不属于当前存储桶')
    return ref[len(prefix):]


def get(ref):
    response = client().get_object(config.MINIO_BUCKET, object_name(ref))
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def signed_url(ref):
    return client().presigned_get_object(config.MINIO_BUCKET, object_name(ref), expires=timedelta(minutes=10))

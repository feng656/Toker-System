"""私有媒体入库；图片去元数据，视频必须实际下载并经ffprobe校验。"""
import hashlib
import io
import json
import subprocess
import tempfile
from pathlib import Path
import httpx
from PIL import Image, UnidentifiedImageError
from fastapi import HTTPException
from sqlalchemy import select
from . import config, storage
from .ai_providers import trusted_url, key
from .models import AIProvider, MediaAsset, VideoJob
from .tasks import lock

MAX_VIDEO_BYTES = 100 * 1024 * 1024


def clean_image(data):
    if not data or len(data) > config.UPLOAD_MAX_BYTES:
        raise HTTPException(413, '图片为空或超过大小限制')
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ('JPEG', 'PNG', 'WEBP') or image.width * image.height > 20_000_000:
                raise ValueError()
            image.load()
            output = io.BytesIO()
            image.convert('RGB').save(output, 'PNG')
            result = output.getvalue()
            if len(result) > config.UPLOAD_MAX_BYTES:
                raise ValueError()
            return result
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
        raise HTTPException(422, '图片须为有效的JPEG/PNG/WebP，像素和大小不得超限')


def save_asset(db, data, *, kind, title, content_type, publicity='internal', tags='', category='', creator_id=None, source='upload'):
    try:
        ref = storage.put(data, 'asset.png' if kind == 'image' else 'asset.mp4', content_type)
    except Exception:
        raise HTTPException(503, '对象存储不可用，素材未入库')
    asset = MediaAsset(kind=kind, title=title[:200], object_ref=ref, content_type=content_type,
                       sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), publicity=publicity,
                       tags=tags, category=category, creator_id=creator_id, source=source)
    db.add(asset)
    db.flush()
    return asset


def download_video(url):
    trusted_url(url, media=True)
    chunks, size = [], 0
    with httpx.stream('GET', url, timeout=60, follow_redirects=False) as response:
        response.raise_for_status()
        for chunk in response.iter_bytes(64 * 1024):
            size += len(chunk)
            if size > MAX_VIDEO_BYTES:
                raise ValueError('视频过大')
            chunks.append(chunk)
    return b''.join(chunks)


def validate_video(data):
    if not data or len(data) > MAX_VIDEO_BYTES:
        raise ValueError('视频为空或过大')
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'output.bin'
        path.write_bytes(data)
        result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
            '-show_format', '-show_streams', '-of', 'json', str(path)],
            capture_output=True, timeout=20, check=True)
        probe = json.loads(result.stdout)
    stream = next((s for s in probe.get('streams', []) if s.get('codec_type') == 'video'), None)
    fmt = probe.get('format', {})
    if not stream or not 0 < float(fmt.get('duration', 0)) <= 600 or not 0 < stream.get('width', 0) <= 7680 or not 0 < stream.get('height', 0) <= 7680:
        raise ValueError('视频缺少有效画面或时长/尺寸超限')
    if not set(fmt.get('format_name', '').split(',')) & {'mov', 'mp4', 'webm', 'matroska'}:
        raise ValueError('仅允许MP4/WebM容器')
    return 'video/webm' if 'webm' in fmt.get('format_name', '') else 'video/mp4'


def video_request(provider, method, path, payload=None, request_key=None):
    endpoint = trusted_url(provider.endpoint)
    headers = {'Authorization': 'Bearer ' + key(provider)}
    if request_key:
        headers['Idempotency-Key'] = request_key
    response = httpx.request(method, endpoint + path, json=payload, headers=headers, timeout=60, follow_redirects=False)
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError('视频适配响应格式错误')
    return result


def run_video(db, job, retry=False):
    lock(db, f'video:{job.id}')
    db.refresh(job)
    if job.status == 'succeeded':
        return job
    if job.status == 'failed' and not retry:
        raise HTTPException(409, '失败任务请显式重试')
    job.attempts += 1
    job.error = ''
    providers = db.scalars(select(AIProvider).where(AIProvider.capability == 'video', AIProvider.enabled.is_(True))
                          .order_by(AIProvider.priority, AIProvider.id)).all()
    if job.provider_id:
        providers = [p for p in providers if p.id == job.provider_id]
    if not providers:
        job.status, job.error = 'failed', '未配置启用的视频适配服务'
        db.commit()
        return job
    for provider in providers[:3]:
        try:
            if not job.remote_job_id:
                payload = {'prompt': job.prompt, 'model': provider.model}
                if job.image_asset_id:
                    asset = db.get(MediaAsset, job.image_asset_id)
                    if not asset or asset.deleted_at or asset.publicity != 'public':
                        raise HTTPException(409, '参考图片未获公开授权')
                    payload['image_url'] = storage.signed_url(asset.object_ref)
                job.provider_id = provider.id  # 网络结果不确定时固定该提供方，重试沿用同键。
                result = video_request(provider, 'POST', '/jobs', payload, f'video:{job.request_key}')
                if not result.get('job_id') or len(str(result['job_id'])) > 200:
                    raise ValueError('视频服务未返回有效job_id')
                job.remote_job_id, job.provider_id = str(result['job_id']), provider.id
                job.status = 'running'
                db.flush()  # 整次调用保持互斥；网络失败仍提交远端ID，后续只能原提供方查询。
            else:
                from urllib.parse import quote
                result = video_request(provider, 'GET', '/jobs/' + quote(job.remote_job_id, safe=''))
            state = result.get('status')
            if state == 'succeeded':
                data = download_video(result.get('output_url', ''))
                mime = validate_video(data)
                asset = save_asset(db, data, kind='video', title=job.prompt[:200], content_type=mime, source='ai')
                job.output_asset_id, job.status = asset.id, 'succeeded'
            elif state in ('queued', 'running'):
                job.status = 'running'
            else:
                raise ValueError('视频任务失败或返回未知状态')
            db.commit()
            return job
        except Exception as exc:
            job.error = type(exc).__name__ + ': 视频服务失败或产物校验不通过；未伪造成品'
            # 网络超时可能已受理，禁止切换导致重复扣费；仅明确的拒绝才允许故障转移。
            if job.remote_job_id or not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code not in (404, 429, 503):
                break
    job.status = 'failed'
    db.commit()
    return job

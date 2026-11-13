"""平台视频生成适配器：提交 → 轮询 → 下载成片，全程留痕到 ai_jobs。

平台接口（πOS）：
  POST {PIOS_API_URL}/agent-api/video/generate  → {task_id, status, model_used, poll_url}
  GET  {PIOS_API_URL}/agent-api/video/tasks/{id} → {status, video_url|preview_url|object_key, ...}

未配置 PIOS_API_URL/PIOS_TOKEN 时明确失败（VideoUnavailable），由调用方决定是否退回
本地占位视频（app/video_gen.py），不把占位产物冒充真实 AI 视频。
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from . import config
from .models import AIJob

TERMINAL_FAILED = ('failed', 'expired', 'cancelled')


class VideoUnavailable(RuntimeError):
    pass


def configured() -> bool:
    return bool(config.PIOS_API_URL and config.PIOS_TOKEN)


def status() -> dict:
    return {'configured': configured(), 'provider': config.VIDEO_PROVIDER,
            'model': config.VIDEO_MODEL, 'resolution': config.VIDEO_RESOLUTION,
            'fallback_model': config.VIDEO_FALLBACK_MODEL,
            'fallback_resolution': config.VIDEO_FALLBACK_RESOLUTION,
            'aspect_ratio': config.VIDEO_ASPECT_RATIO, 'duration_sec': config.VIDEO_DURATION_SEC,
            'watermark': config.VIDEO_WATERMARK}


def _headers() -> dict:
    return {'Authorization': 'Bearer ' + config.PIOS_TOKEN}


def _api(path: str) -> str:
    return config.PIOS_API_URL + path


def submit(prompt: str, *, duration_sec: Optional[int] = None, resolution: Optional[str] = None,
           aspect_ratio: Optional[str] = None, model: Optional[str] = None,
           ref_image_base64: Optional[str] = None, seed: Optional[int] = None) -> dict:
    """提交异步视频任务，返回平台受理回执（含 task_id）。

    主模型上游偶发 502 时自动换备用模型重试一次；429/503 是排队或限流，不重试。
    """
    if not configured():
        raise VideoUnavailable('未配置平台视频服务（PIOS_API_URL / PIOS_TOKEN）')

    def body_for(use_model: str, use_resolution: str) -> dict:
        body: dict = {
            'async_mode': True,
            'prompt': prompt,
            'duration_sec': int(duration_sec or config.VIDEO_DURATION_SEC),
            'aspect_ratio': aspect_ratio or config.VIDEO_ASPECT_RATIO,
            'watermark': config.VIDEO_WATERMARK,
        }
        if use_resolution:
            body['resolution'] = use_resolution
        if use_model:
            body['model'] = use_model
        if ref_image_base64:
            body['ref_image_base64'] = ref_image_base64
        if seed is not None:
            body['seed'] = seed
        return body

    use_model = model or config.VIDEO_MODEL
    use_resolution = resolution or config.VIDEO_RESOLUTION
    r = httpx.post(_api('/agent-api/video/generate'), headers=_headers(),
                   json=body_for(use_model, use_resolution),
                   timeout=max(config.VIDEO_TIMEOUT, 660.0), follow_redirects=False)
    if r.status_code == 502 and config.VIDEO_FALLBACK_MODEL and config.VIDEO_FALLBACK_MODEL != use_model:
        r = httpx.post(_api('/agent-api/video/generate'), headers=_headers(),
                       json=body_for(config.VIDEO_FALLBACK_MODEL,
                                     config.VIDEO_FALLBACK_RESOLUTION or use_resolution),
                       timeout=max(config.VIDEO_TIMEOUT, 660.0), follow_redirects=False)
    if r.status_code in (429, 503):
        retry_after = ''
        try:
            retry_after = str((r.json() or {}).get('retry_after_s', ''))
        except ValueError:
            pass
        raise VideoUnavailable('上游限流或队列已满' + (f'，{retry_after} 秒后重试' if retry_after else ''))
    r.raise_for_status()
    data = _unwrap(r.json())
    if not isinstance(data, dict) or data.get('task_id') is None:
        raise VideoUnavailable('平台未返回 task_id')
    return data


def _unwrap(payload) -> dict:
    """平台统一响应为 {success, message, data}；兼容直接返回业务字段的旧/简化形态。"""
    if isinstance(payload, dict) and isinstance(payload.get('data'), dict):
        return payload['data']
    return payload if isinstance(payload, dict) else {}


def poll(task_id: int) -> dict:
    r = httpx.get(_api(f'/agent-api/video/tasks/{task_id}'), headers=_headers(),
                  timeout=60, follow_redirects=False)
    r.raise_for_status()
    data = _unwrap(r.json())
    if not data:
        raise VideoUnavailable('平台任务状态返回结构无效')
    return data


def wait(task_id: int, *, interval: Optional[float] = None,
         timeout: Optional[float] = None) -> dict:
    """轮询到终态；成功返回任务回执，失败抛 VideoUnavailable。"""
    interval = config.VIDEO_POLL_INTERVAL if interval is None else interval
    deadline = time.monotonic() + (config.VIDEO_TIMEOUT if timeout is None else timeout)
    data: dict = {'task_id': task_id, 'status': 'pending'}
    while True:
        state = data.get('status')
        if state in TERMINAL_FAILED:
            raise VideoUnavailable(str(data.get('error') or f'视频任务{state}'))
        if state == 'succeeded' and (data.get('video_url') or data.get('preview_url')
                                     or data.get('object_key') or data.get('video_base64')):
            return data
        if time.monotonic() >= deadline:
            raise VideoUnavailable(f'等待视频任务超时（task_id={task_id}），可稍后查询')
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))
        try:
            data = poll(task_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 500, 502, 503, 504):
                continue
            raise


def download(data: dict, out_path: Path) -> Path:
    """把成片落盘：优先内联 base64，其次 preview_url/video_url，最后 object_key 提示。"""
    import base64
    out_path.parent.mkdir(parents=True, exist_ok=True)
    inline = data.get('video_base64')
    if inline:
        out_path.write_bytes(base64.b64decode(inline))
        return out_path
    url = data.get('video_url') or data.get('preview_url') or ''
    if url:
        # preview_url 是平台相对路径（/api/v1/files/preview?...），需拼回 API 根。
        if url.startswith('/'):
            base = config.PIOS_API_URL
            if url.startswith('/api/v1') and base.endswith('/api/v1'):
                url = base[:-len('/api/v1')] + url
            else:
                url = base + url
        r = httpx.get(url, headers=_download_headers(url), timeout=120, follow_redirects=True)
        r.raise_for_status()
        out_path.write_bytes(r.content)
        return out_path
    raise VideoUnavailable('平台未返回可下载地址，object_key=' + str(data.get('object_key') or ''))


def _download_headers(url: str) -> dict:
    """只给平台同源地址带令牌；成片可能托管在第三方 CDN，不能把平台令牌发过去。"""
    from urllib.parse import urlparse
    if urlparse(url).netloc == urlparse(config.PIOS_API_URL).netloc:
        return _headers()
    return {}


def generate(db: Session, prompt: str, *, out_path: Optional[Path] = None,
             resource_id=None, duration_sec: Optional[int] = None,
             resolution: Optional[str] = None, aspect_ratio: Optional[str] = None,
             model: Optional[str] = None, ref_image_base64: Optional[str] = None,
             seed: Optional[int] = None) -> dict:
    """端到端：提交 → 轮询 → 下载，写一条 ai_jobs 审计。返回 {path, task_id, ...}。"""
    digest = hashlib.sha256(prompt.encode()).hexdigest()
    job = AIJob(kind='video', resource_id=resource_id, input_hash=digest,
                provider=config.VIDEO_PROVIDER, model=model or config.VIDEO_MODEL)
    db.add(job)
    # 提交审计行后再等待上游：轮询期间不占着事务，SQLite 演示模式下也不阻塞其他请求。
    db.commit()
    start = time.monotonic()
    try:
        receipt = submit(prompt, duration_sec=duration_sec, resolution=resolution,
                         aspect_ratio=aspect_ratio, model=model,
                         ref_image_base64=ref_image_base64, seed=seed)
        task_id = int(receipt['task_id'])
        data = wait(task_id)
        target = out_path or (config.VIDEO_OUTPUT_DIR / f'video_{task_id}.mp4')
        path = download(data, Path(target))
        result = {'task_id': task_id, 'path': str(path),
                  'model_used': data.get('model_used') or receipt.get('model_used') or '',
                  'duration_sec': data.get('duration_sec') or data.get('duration_seconds'),
                  'credits_charged': data.get('credits_charged'),
                  'object_key': data.get('object_key') or '',
                  'content_id': data.get('content_id')}
        job.status, job.output = 'succeeded', result
        if result.get('model_used'):
            job.model = result['model_used']
        return result
    except Exception as exc:
        # 不记录可能携带凭据的异常正文。
        job.status = 'failed'
        job.error = type(exc).__name__ + ': 视频生成失败'
        raise
    finally:
        job.duration_ms = int((time.monotonic() - start) * 1000)
        db.flush()

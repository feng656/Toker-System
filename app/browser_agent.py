"""浏览器能力使用显式配置的受控适配服务，不在后端私启隐藏浏览器。
适配契约见 docs/ADAPTERS.md；默认关闭。填稿成功不等于发布成功。
"""
import httpx
from fastapi import HTTPException
from . import config
from .generator import apply_compliance, ensure_current, record_publication

STORAGE_DIR = config.BROWSER_STATE_DIR
PLATFORMS = ('gzh', 'douyin', 'shipinhao', 'xhs')


def check(platform):
    if platform not in PLATFORMS:
        raise HTTPException(422, '不支持的平台')
    if not config.BROWSER_ENABLED or not config.BROWSER_ADAPTER_URL:
        raise HTTPException(503, '浏览器填稿为实验适配能力，尚未配置；请先使用人工复制发布')


async def request(platform, action, payload=None):
    check(platform)
    headers = {'Authorization': 'Bearer ' + config.BROWSER_ADAPTER_TOKEN} if config.BROWSER_ADAPTER_TOKEN else {}
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        response = await client.post(config.BROWSER_ADAPTER_URL.rstrip('/') + f'/{platform}/{action}',
                                     json=payload or {}, headers=headers)
        response.raise_for_status()
        return response.json()


async def open_platform(platform):
    try:
        return await request(platform, 'open')
    except httpx.HTTPError:
        raise HTTPException(502, '受控浏览器适配服务不可用')


async def screenshot(platform):
    try:
        return await request(platform, 'screenshot')
    except httpx.HTTPError:
        raise HTTPException(502, '受控浏览器适配服务不可用')


async def fill_variant(db, v):
    ensure_current(v)
    if v.confirm_status != 'confirmed' or v.status == 'published':
        raise HTTPException(409, '仅可提交已审核、未发布版本')
    if not apply_compliance(db, v):
        db.commit()
        raise HTTPException(409, '合规校验未通过')
    v.publish_status, v.publish_error = 'publishing', ''
    db.commit()
    try:
        result = await request(v.platform, 'fill', {'variant_id': v.id, 'title': v.cover_text or v.content.title,
                    'body': v.body, 'assets_url': v.assets_url})
        v.publish_result = result
        if not result.get('ok'):
            raise ValueError('适配服务填稿失败')
        if result.get('published') and result.get('url'):
            record_publication(db, v, result['url'])
        else:
            v.publish_status = 'filled'
        db.commit()
        return {'variant_id': v.id, 'publish_status': v.publish_status, 'result': result}
    except Exception as exc:
        v.publish_status = 'failed'
        v.publish_error = (exc.detail if isinstance(exc, HTTPException) else
                           str(exc) if isinstance(exc, ValueError) else type(exc).__name__ + ': 浏览器填稿失败')
        db.commit()
        return {'variant_id': v.id, 'publish_status': 'failed', 'error': v.publish_error, 'retryable': True}

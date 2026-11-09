"""受信浏览器适配：会话加密、发布预览/确认、真实截图存证。
适配服务负责可见浏览器和平台许可；这里不启动隐藏浏览器、不伪造登录成功。
"""
import base64
import hashlib
import json
from datetime import datetime, timezone
import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import select
from . import config, storage
from .db import utcnow
from .models import Platform, WorkspaceAccount, WorkspaceJob, ContentVariant, AssetUsage, MediaAsset, AutomationEvent
from .tasks import lock


def cipher():
    try:
        return Fernet(config.SESSION_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError):
        raise HTTPException(503, '未配置有效的SESSION_ENCRYPTION_KEY，拒绝持久化账号会话')


def encrypt(value):
    return cipher().encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()


def decrypt(value):
    try:
        return json.loads(cipher().decrypt(value.encode()))
    except (InvalidToken, ValueError):
        raise HTTPException(409, '会话无法解密，请重新登录')


def event(db, resource, resource_id, action, actor_id=None, detail=None):
    db.add(AutomationEvent(resource=resource, resource_id=resource_id, action=action,
                           actor_id=actor_id, detail=detail or {}))


def request(action, payload, request_key=None):
    from .ai_providers import trusted_url
    if not config.BROWSER_ENABLED or not config.BROWSER_ADAPTER_URL or not config.BROWSER_ADAPTER_TOKEN:
        raise HTTPException(503, '未配置受信浏览器适配服务及认证，不能执行真实平台操作')
    url = trusted_url(config.BROWSER_ADAPTER_URL)
    headers = {'Authorization': 'Bearer ' + config.BROWSER_ADAPTER_TOKEN}
    if request_key:
        headers['Idempotency-Key'] = request_key
    try:
        response = httpx.post(url + '/v2/' + action, json=payload, headers=headers, timeout=60, follow_redirects=False)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or data.get('ok') is not True:
            raise ValueError('invalid response')
        return data
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, '适配服务失败或响应无效；请核对远端状态，不盲目重复发送')


def expiry(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        result = result.astimezone(timezone.utc).replace(tzinfo=None)
        if result <= utcnow():
            raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(502, '适配服务返回了无效或过期的期限')


def account_payload(db, account):
    platform = db.get(Platform, account.platform_id)
    if not platform or platform.deleted_at or not platform.enabled:
        raise HTTPException(409, '账号平台已停用')
    if account.status != 'connected' or not account.session_expires_at or account.session_expires_at <= utcnow():
        raise HTTPException(409, '账号未登录或会话已过期，请重新扫码')
    return {'account_id': account.id, 'platform': platform.code, 'session': decrypt(account.session_ciphertext)}


def public_account(account):
    from .api import as_dict
    result = as_dict(account, {'session_ciphertext', 'login_attempt_id', 'qr_object_ref'})
    now = utcnow()
    if account.status == 'connected' and (not account.session_expires_at or account.session_expires_at <= now):
        result['status'] = 'expired'
    result['expires_soon'] = bool(account.session_expires_at and (account.session_expires_at-now).total_seconds() < 600)
    result['qr_available'] = bool(account.qr_object_ref and account.qr_expires_at and account.qr_expires_at > now)
    return result


def apply_login(account, data):
    if data.get('status') == 'connected':
        if not isinstance(data.get('session'), dict) or not data['session']:
            raise HTTPException(502, '登录响应缺少真实会话')
        account.session_expires_at = expiry(data.get('expires_at'))
        account.session_ciphertext = encrypt(data['session'])
        account.status, account.error = 'connected', ''
        account.nickname = str(data.get('nickname', ''))[:100]
        account.avatar_url = str(data.get('avatar_url', ''))[:700]
        account.qr_object_ref, account.qr_expires_at = '', None
    elif data.get('status') == 'awaiting_scan':
        from .media import clean_image
        if not data.get('attempt_id') or len(str(data['attempt_id'])) > 200:
            raise HTTPException(502, '缺少扫码会话标识')
        try:
            raw = data['qr_png_base64']
            if len(raw) > config.UPLOAD_MAX_BYTES * 2:
                raise ValueError()
            png = clean_image(base64.b64decode(raw, validate=True))
        except (KeyError, ValueError):
            raise HTTPException(502, '二维码图片无效')
        account.qr_expires_at = expiry(data.get('expires_at'))
        account.qr_object_ref = storage.put(png, 'login-qr.png', 'image/png')
        account.login_attempt_id = str(data['attempt_id'])
        account.status = 'awaiting_scan'
    elif data.get('status') == 'expired':
        account.status, account.qr_object_ref = 'expired', ''
    else:
        raise HTTPException(502, '未知登录状态，未记录登录成功')


def login(db, account, body, actor_id):
    cipher()  # 密钥缺失时不能把账号密码发送到外部。
    lock(db, f'account:{account.id}')
    platform = db.get(Platform, account.platform_id)
    if not platform.enabled:
        raise HTTPException(409, '平台已停用')
    if body.login_mode == 'password' and (not body.username or not body.password):
        raise HTTPException(422, '账密登录必须提供账号和密码')
    data = request('accounts/login', {'account_id': account.id, 'platform': platform.code,
        'mode': body.login_mode, 'username': body.username, 'password': body.password})
    apply_login(account, data)
    event(db, 'account', account.id, 'login_' + account.status, actor_id)
    db.commit()
    return public_account(account)


def refresh(db, account, actor_id):
    lock(db, f'account:{account.id}')
    payload = {'account_id': account.id, 'attempt_id': account.login_attempt_id}
    if account.status == 'connected':
        payload['session'] = decrypt(account.session_ciphertext)
    data = request('accounts/refresh', payload)
    apply_login(account, data)
    event(db, 'account', account.id, 'refresh_' + account.status, actor_id)
    db.commit()
    return public_account(account)


def logout(db, account, actor_id):
    lock(db, f'account:{account.id}')
    # 远端必须确认撤销；不可把本地清空伪称远端登出。
    request('accounts/logout', {'account_id': account.id, 'attempt_id': account.login_attempt_id,
        'session': decrypt(account.session_ciphertext) if account.session_ciphertext else {}})
    account.session_ciphertext, account.login_attempt_id, account.qr_object_ref = '', '', ''
    account.session_expires_at = account.qr_expires_at = None
    account.status = 'disconnected'
    event(db, 'account', account.id, 'logout', actor_id)
    db.commit()


def fingerprint(v, assets):
    return hashlib.sha256(json.dumps({'body':v.body, 'title':v.cover_text or v.content.title,
        'hashtags':v.hashtags, 'assets':[a.id for a in assets]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def eligible(db, job):
    from .generator import apply_compliance, ensure_current
    v = db.get(ContentVariant, job.variant_id)
    a = db.get(WorkspaceAccount, job.account_id)
    if not v or v.deleted_at or not a or a.deleted_at:
        raise HTTPException(409, '账号或内容不存在')
    ensure_current(v)
    if v.platform_id != a.platform_id or v.confirm_status != 'confirmed' or v.status != 'pending':
        raise HTTPException(409, '只能发布同平台、已审核未发布的当前版本')
    if not apply_compliance(db, v):
        db.commit()
        raise HTTPException(409, '合规规则已变更，禁止发布')
    assets = db.scalars(select(MediaAsset).join(AssetUsage, AssetUsage.asset_id == MediaAsset.id)
                       .where(AssetUsage.variant_id == v.id).order_by(MediaAsset.id)).all()
    if any(x.publicity != 'public' for x in assets):
        raise HTTPException(409, '引用素材未经公开授权')
    return v, a, assets


def steps(data):
    from .media import clean_image
    result = []
    for item in data.get('steps', [])[:20]:
        entry = {'name': str(item.get('name', ''))[:100], 'status': str(item.get('status', ''))[:30]}
        raw = item.get('screenshot_png_base64')
        if raw:
            if len(raw) > config.UPLOAD_MAX_BYTES * 2:
                raise ValueError('截图过大')
            entry['screenshot_ref'] = storage.put(clean_image(base64.b64decode(raw, validate=True)), 'step.png', 'image/png')
        result.append(entry)
    if not any('screenshot_ref' in x for x in result):
        raise ValueError('真实发布步骤必须附截图证据')
    return result


def public_job(job):
    from .api import as_dict
    return as_dict(job, {'confirmation_token'})


def run_publish(db, job, actor_id, confirm=False, retry=False):
    lock(db, f'workspace-job:{job.id}')
    db.refresh(job)
    if job.status == 'succeeded':
        return public_job(job)
    allowed = ('awaiting_confirmation',) if confirm else (('failed',) if retry else ('queued',))
    if job.status not in allowed:
        raise HTTPException(409, '任务状态不允许此操作')
    lock(db, f'publish-variant:{job.variant_id}')
    lock(db, f'account:{job.account_id}')
    v, account, assets = eligible(db, job)
    payload = account_payload(db, account)
    digest = fingerprint(v, assets)
    if confirm:
        confirmation = decrypt(job.confirmation_token)
        if confirmation.get('fingerprint') != digest:
            raise HTTPException(409, '内容或素材已改变，请取消任务并重新预览')
        payload.update(remote_job_id=job.remote_job_id, confirmation_token=confirmation['token'], human_confirmed=True)
    else:
        payload.update(variant_id=v.id, title=v.cover_text or v.content.title, body=v.body, hashtags=v.hashtags,
            assets=[{'kind':a.kind, 'url':storage.signed_url(a.object_ref)} for a in assets], submit=False)
    job.attempts += 1
    try:
        data = request('publish/confirm' if confirm else 'publish/prepare', payload,
                       f'publish:{job.request_key}:' + ('confirm' if confirm else 'prepare'))
        evidence = steps(data)
        if confirm:
            if data.get('status') != 'published' or not data.get('url'):
                raise ValueError('缺少真实发布结果')
            from .generator import record_publication
            record_publication(db, v, data['url'])
            job.status, job.confirmed_by = 'succeeded', actor_id
            job.steps = job.steps + evidence
        else:
            if data.get('status') != 'awaiting_confirmation' or not data.get('confirmation_token') or not data.get('job_id'):
                raise ValueError('预览不得直接发布，必须等待人工确认')
            job.remote_job_id = str(data['job_id'])[:200]
            job.confirmation_token = encrypt({'token':data['confirmation_token'], 'fingerprint':digest})
            job.status, job.steps = 'awaiting_confirmation', evidence
        job.error = ''
        event(db, 'publish', job.id, job.status, actor_id, {'variant_id':v.id})
    except Exception as exc:
        # confirm超时可能已发布：保留待确认及相同幂等键，不能重建任务再盲发。
        job.status = 'awaiting_confirmation' if confirm else 'failed'
        job.error = type(exc).__name__ + ': 发布适配失败，核对远端状态后用同任务重试'
        event(db, 'publish', job.id, 'failed', actor_id)
    db.commit()
    return public_job(job)

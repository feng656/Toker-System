"""统一AI配置与出站目标约束。数据库仅持有环境变量名称，不保存key明文。"""
import os
from urllib.parse import urlsplit
from fastapi import HTTPException
from sqlalchemy import select
from . import config
from .models import AIProvider


def trusted_url(value, media=False):
    try:
        u = urlsplit(value)
        host = (u.hostname or '').lower()
        if u.scheme not in ('https', 'http') or not host or u.username or u.password or u.fragment:
            raise ValueError()
        allowed = config.MEDIA_ALLOWED_HOSTS if media else config.ADAPTER_ALLOWED_HOSTS
        if host not in allowed or (u.query and not media):
            raise ValueError()
        _ = u.port  # 验证端口；仅部署人员可授权内网适配器，UI不能扩大白名单。
        return value.rstrip('/')
    except (ValueError, OSError):
        raise HTTPException(422, '目标必须在部署环境的主机白名单内，禁止URL凭据和适配端点查询参数')


def key(provider):
    return os.getenv(provider.key_env, '') if provider.key_env and provider.key_env.startswith('TOKER_AI_KEY_') else ''


def text_providers(db, provider_id=None):
    query = select(AIProvider).where(AIProvider.enabled.is_(True), AIProvider.capability == 'text').order_by(AIProvider.priority, AIProvider.id)
    if provider_id:
        query = query.where(AIProvider.id == provider_id)
    rows = db.scalars(query).all()
    if rows:
        return [{'name':p.name,'base_url':trusted_url(p.endpoint),'model':p.model,'key':key(p)} for p in rows]
    return [] if provider_id else config.LLM_PROVIDERS


def public_config(provider):
    return {c.name:getattr(provider,c.name) for c in provider.__table__.columns if c.name != 'deleted_at'} | {'configured':bool(key(provider))}

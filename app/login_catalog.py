"""账号登录目录独立于内容生成范围；预置选项不等于已接通平台登录。"""
import ipaddress
from urllib.parse import urlsplit
from fastapi import HTTPException
from sqlalchemy import select
from . import config
from .models import Platform

CATALOG = [
    ('douyin', '抖音', 'video', 'https://creator.douyin.com/'),
    ('xhs', '小红书', 'text', 'https://creator.xiaohongshu.com/'),
    ('kuaishou', '快手', 'video', 'https://cp.kuaishou.com/'),
    ('bilibili', '哔哩哔哩', 'video', 'https://member.bilibili.com/'),
    ('shipinhao', '微信视频号', 'video', 'https://channels.weixin.qq.com/'),
    ('gzh', '微信公众号', 'text', 'https://mp.weixin.qq.com/'),
    ('weibo', '微博', 'text', 'https://weibo.com/'),
    ('zhihu', '知乎', 'text', 'https://www.zhihu.com/'),
    ('toutiao', '今日头条', 'text', 'https://mp.toutiao.com/'),
    ('baijiahao', '百家号', 'text', 'https://baijiahao.baidu.com/'),
    ('taobao', '淘宝', 'commerce', 'https://www.taobao.com/'),
    ('jd', '京东', 'commerce', 'https://www.jd.com/'),
    ('pinduoduo', '拼多多', 'commerce', 'https://mms.pinduoduo.com/'),
    ('xianyu', '闲鱼', 'commerce', 'https://www.goofish.com/'),
    ('alibaba1688', '1688', 'commerce', 'https://www.1688.com/'),
]
CATALOG_CODES = {item[0] for item in CATALOG}


def validate_login_url(value):
    """仅作人工打开入口，不交给适配器任意导航；禁止凭据/内网/非HTTPS。"""
    if not value:
        return ''
    try:
        u = urlsplit(value)
        host = (u.hostname or '').lower().rstrip('.')
        if (u.scheme != 'https' or not host or u.username or u.password or u.fragment or u.query
            or u.port not in (None, 443) or any(c.isspace() or ord(c) < 32 for c in value)
            or '\\' in value or '%' in host or '.' not in host
            or host.endswith(('.localhost', '.local', '.internal', '.test', '.invalid'))):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if (address and not address.is_global) or (address is None and host.split('.')[-1].isdigit()):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise ValueError('平台登录入口须为公开HTTPS网址，不能带账号密码、查询参数或内网地址')


def login_capability(platform):
    if platform.code == 'moments':
        return {'qr_status': 'unsupported', 'qr_message': '朋友圈没有独立网页版扫码登录，请使用微信客户端。'}
    if not platform.enabled:
        return {'qr_status': 'disabled', 'qr_message': '该平台已停用，管理员明确启用后才能登录。'}
    if not config.BROWSER_ENABLED or not config.BROWSER_ADAPTER_URL or not config.BROWSER_ADAPTER_TOKEN:
        return {'qr_status': 'unconfigured', 'qr_message': '账号可以保存；管理员接通此平台的真实扫码服务后才能获取登录二维码。'}
    if config.BROWSER_LOGIN_PLATFORMS and platform.code not in config.BROWSER_LOGIN_PLATFORMS:
        return {'qr_status': 'unsupported', 'qr_message': '当前扫码服务尚未接入此平台，账号可以先保存。'}
    try:
        from cryptography.fernet import Fernet
        Fernet(config.SESSION_ENCRYPTION_KEY.encode())
        from .ai_providers import trusted_url
        trusted_url(config.BROWSER_ADAPTER_URL)
    except (ValueError, TypeError, HTTPException):
        return {'qr_status': 'unconfigured', 'qr_message': '扫码服务的会话加密密钥或可信地址配置尚未完成，请联系管理员。'}
    return {'qr_status': 'configured', 'qr_message': '已配置扫码服务，二维码由目标平台签发；实际可用性以获取结果为准。'}


def catalog(db):
    order = {code: i for i, (code, *_) in enumerate(CATALOG)}
    names = {code: name for code, name, *_ in CATALOG}
    rows = db.scalars(select(Platform)).all()
    rows = sorted(rows, key=lambda p: (order.get(p.code, 1000), p.id))
    return [{
        'id': p.id, 'code': p.code, 'name': names.get(p.code, p.name) if p.name == p.code else p.name, 'category': p.category,
        'enabled': p.enabled, 'generation_enabled': p.generation_enabled,
        'login_url': p.login_url, 'builtin': p.code in CATALOG_CODES,
        'version': p.version, **login_capability(p),
    } for p in rows if p.code != 'moments']


def check_login_platform(platform):
    if not platform or platform.deleted_at:
        raise HTTPException(409, '账号关联的平台不存在或已删除')
    capability = login_capability(platform)
    if capability['qr_status'] in ('unsupported', 'disabled'):
        raise HTTPException(409, capability['qr_message'])

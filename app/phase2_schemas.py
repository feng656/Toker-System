import re
from datetime import date
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from .schemas import Input, Platform, VersionIn


class PlatformIn(Input):
    code: Platform
    name: str = Field(min_length=1, max_length=100)
    icon: str = Field(default='', max_length=300)
    category: Literal['text', 'video', 'commerce', 'other'] = 'text'
    publish_mode: Literal['manual', 'sandbox', 'api'] = 'manual'
    default_time: str = Field(default='18:00-20:00', max_length=100)
    style_prompt: str = Field(default='', max_length=3000)
    enabled: bool = True
    expected_version: int | None = None
    generation_enabled: bool | None = None
    login_url: str | None = Field(default=None, max_length=700)

    @field_validator('login_url')
    @classmethod
    def valid_login_url(cls, value):
        from .login_catalog import validate_login_url
        return validate_login_url(value) if value is not None else value


class LoginPlatformIn(Input):
    name: str = Field(min_length=1, max_length=100)
    code: Platform | None = None
    category: Literal['text', 'video', 'commerce', 'other'] = 'other'
    login_url: str = Field(default='', max_length=700)
    request_key: str = Field(min_length=16, max_length=100)

    @field_validator('login_url')
    @classmethod
    def valid_login_url(cls, value):
        from .login_catalog import validate_login_url
        return validate_login_url(value)


class BulkReviewIn(Input):
    variant_ids: list[int] = Field(min_length=1, max_length=100)
    action: Literal['approve', 'reject']
    reason: str = Field(default='', max_length=2000)
    expected_versions: dict[str, int] = Field(default_factory=dict)


class DraftIn(Input):
    title: str = Field(min_length=1, max_length=200)
    platform_id: int = Field(gt=0)
    body: str = Field(min_length=1, max_length=30000)
    biz_line: Literal['project', 'channel'] = 'project'
    scheduled_date: date | None = None
    asset_ids: list[int] = Field(default_factory=list, max_length=50)


class AssetUpdate(Input):
    title: str = Field(min_length=1, max_length=200)
    publicity: Literal['public', 'internal', 'masked'] = 'internal'
    tags: str = Field(default='', max_length=500)
    category: str = Field(default='', max_length=100)
    expected_version: int | None = None


class AssetGenerateIn(Input):
    request_key: str = Field(min_length=1, max_length=140)
    topic_id: int = Field(gt=0)
    platform_id: int = Field(gt=0)
    asset_ids: list[int] = Field(min_length=1, max_length=20)
    scheduled_date: date | None = None


class AssetLinkIn(Input):
    asset_ids: list[int] = Field(min_length=1, max_length=20)
    expected_version: int | None = None


class ProviderIn(Input):
    name: str = Field(min_length=1, max_length=100)
    capability: Literal['text', 'video'] = 'text'
    endpoint: str = Field(max_length=500)
    model: str = Field(min_length=1, max_length=100)
    key_env: str = Field(default='', max_length=100, pattern=r'^(?:TOKER_AI_KEY_[A-Z0-9_]+)?$')
    priority: int = Field(default=100, ge=0, le=1000)
    enabled: bool = True
    expected_version: int | None = None


class VideoIn(Input):
    request_key: str = Field(min_length=1, max_length=150)
    prompt: str = Field(min_length=1, max_length=5000)
    image_asset_id: int | None = Field(default=None, gt=0)
    platform_id: int | None = Field(default=None, gt=0)
    provider_id: int | None = Field(default=None, gt=0)


class AccountIn(Input):
    platform_id: int = Field(gt=0)
    label: str = Field(min_length=1, max_length=100)
    login_hint: str = Field(default='', max_length=200)
    request_key: str | None = Field(default=None, min_length=16, max_length=100)


class AccountLoginIn(Input):
    login_mode: Literal['qr', 'password'] = 'qr'
    username: str = Field(default='', max_length=200)
    password: str = Field(default='', max_length=300)
    # 用户主动点“扫码登录/重新获取”时必须换一张新码；默认复用未过期二维码
    # 只用于网络重试等幂等场景，避免把剩余寿命很短的旧码当成新码展示。
    fresh: bool = False


class ImportCookieIn(BaseModel):
    """兼容 Chrome chrome.cookies.getAll() 的输出字段；多余字段忽略。"""
    model_config = ConfigDict(extra='ignore')

    name: str = Field(min_length=1, max_length=200)
    value: str = Field(default='', max_length=4096)
    domain: str = Field(min_length=1, max_length=300)
    path: str = Field(default='/', max_length=300)
    expires: float | None = None
    expirationDate: float | None = None
    httpOnly: bool = False
    secure: bool = True
    sameSite: str | None = None
    hostOnly: bool | None = None
    session: bool | None = None

    @field_validator('name')
    @classmethod
    def safe_name(cls, value):
        if not re.fullmatch(r'[A-Za-z0-9_.\-]+', value):
            raise ValueError('Cookie 名称包含非法字符')
        return value

    @field_validator('path')
    @classmethod
    def safe_path(cls, value):
        return value if value.startswith('/') else '/'


class ImportSessionPayloadIn(BaseModel):
    model_config = ConfigDict(extra='ignore')

    cookies: list[ImportCookieIn] = Field(min_length=1, max_length=60)
    nickname: str = Field(default='', max_length=100)
    avatar_url: str = Field(default='', max_length=700)


class SessionImportIn(BaseModel):
    model_config = ConfigDict(extra='forbid')

    platform: str = Field(min_length=1, max_length=50)
    session: ImportSessionPayloadIn


class PublishJobIn(Input):
    request_key: str = Field(min_length=1, max_length=150)
    account_id: int = Field(gt=0)
    variant_id: int = Field(gt=0)


class CommentTaskIn(Input):
    account_id: int = Field(gt=0)
    keyword: str = Field(min_length=1, max_length=200)
    mode: Literal['manual', 'polish', 'ai'] = 'manual'
    draft: str = Field(default='', max_length=10000)
    video_limit: int = Field(default=5, ge=1, le=5)
    comments_per_video: int = Field(default=10, ge=1, le=10)
    date_from: date | None = None
    sort_order: Literal['latest', 'popular'] = 'latest'


class DiscoverIn(Input):
    search_confirmed: bool


class ReplyTemplateIn(Input):
    name: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=3000)
    enabled: bool = True


class DMPolicyIn(Input):
    account_id: int = Field(gt=0)
    mode: Literal['fixed', 'ai'] = 'fixed'
    template_id: int | None = Field(default=None, gt=0)
    provider_id: int | None = Field(default=None, gt=0)
    persona: str = Field(default='', max_length=3000)
    window_start: str = '09:00'
    window_end: str = '18:00'
    scope: list[str] = Field(default_factory=list, max_length=100)
    enabled: bool = False

    @field_validator('window_start', 'window_end')
    @classmethod
    def time_value(cls, value):
        from datetime import time
        time.fromisoformat(value)
        if len(value) != 5:
            raise ValueError('时段必须HH:MM')
        return value


class DMIn(Input):
    source_key: str = Field(min_length=1, max_length=200)
    account_id: int = Field(gt=0)
    sender_id: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)

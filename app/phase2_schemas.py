from datetime import date
from typing import Literal
from pydantic import Field, field_validator
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


class AccountLoginIn(Input):
    login_mode: Literal['qr', 'password'] = 'qr'
    username: str = Field(default='', max_length=200)
    password: str = Field(default='', max_length=300)


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

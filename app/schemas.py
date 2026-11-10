from datetime import date
import ipaddress
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator

from typing import Annotated
Platform = Annotated[str, Field(min_length=1, max_length=40, pattern=r'^[a-z][a-z0-9_-]*$')]
Role = Literal['admin', 'operator', 'sales']
LeadStatus = Literal['new', 'contacted', 'opportunity', 'won', 'lost', 'invalid']


def valid_publish_url(value: str) -> str:
    value = value.strip()
    if len(value) > 1000 or any(c.isspace() for c in value):
        raise ValueError('发布链接长度或格式错误')
    try:
        u = urlsplit(value)
        host = (u.hostname or '').lower()
        _ = u.port
        if u.scheme not in ('http', 'https') or not host or u.username or u.password:
            raise ValueError()
        if '.' not in host or host.endswith(('.local', '.internal', '.localhost', '.test', '.invalid', '.example')):
            raise ValueError()
        if not u.path.strip('/'):
            raise ValueError()
        if host in ('example.com', 'example.org', 'example.net'):
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('须回填真实公开的 HTTP(S) 发布链接，不能使用空值、本机地址或平台内部编号')
    return value


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class LoginIn(Input):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=72)
    invite_code: str | None = Field(default=None, max_length=200)
    challenge_id: str | None = Field(default=None, max_length=64)
    challenge_solution: str | None = Field(default=None, max_length=100)


class PasswordIn(Input):
    old_password: str
    new_password: str = Field(min_length=10, max_length=72)


class MaterialIn(Input):
    category: str = Field(min_length=1, max_length=30)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(default='', max_length=20000)
    biz_line: Literal['project', 'channel', 'both'] = 'both'
    publicity: Literal['public', 'masked', 'internal'] = 'public'
    tags: str = Field(default='', max_length=200)
    file_url: str = Field(default='', max_length=500)
    enabled: bool = True
    expected_version: int | None = None


class TopicIn(Input):
    biz_line: Literal['project', 'channel']
    theme: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=200)
    angle: str = Field(default='', max_length=5000)


class VersionIn(Input):
    expected_version: int | None = None


class VariantUpdate(VersionIn):
    body: str | None = Field(default=None, min_length=1, max_length=30000)
    cover_text: str | None = Field(default=None, max_length=200)
    hashtags: str | None = Field(default=None, max_length=500)


class ReviewIn(VersionIn):
    action: Literal['approve', 'reject']
    note: str = Field(default='', max_length=2000)


class RejectIn(VersionIn):
    reason: str = Field(min_length=1, max_length=2000)


class PublishIn(VersionIn):
    published_url: str
    _url = field_validator('published_url')(valid_publish_url)


class MetricIn(Input):
    variant_id: int = Field(gt=0)
    stat_date: date
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    collects: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    new_fans: int = Field(default=0, ge=0)
    dm_inquiries: int = Field(default=0, ge=0)


class InteractionIn(Input):
    platform: Platform
    body: str = Field(min_length=1, max_length=10000)
    kind: Literal['comment', 'dm'] = 'comment'
    author_name: str = Field(default='', max_length=100)
    author_id: str = Field(default='', max_length=100)
    variant_id: int | None = Field(default=None, gt=0)
    auto_classify: bool = True
    source_key: str | None = Field(default=None, min_length=1, max_length=150)


class LeadUpdate(VersionIn):
    status: LeadStatus | None = None
    assignee: str | None = Field(default=None, max_length=50)
    follow_notes: str | None = Field(default=None, max_length=5000)


class RuleIn(Input):
    rule_type: Literal['forbidden', 'required', 'ad_law']
    pattern: str = Field(min_length=1, max_length=200)
    note: str = Field(default='', max_length=200)
    enabled: bool = True


class UserIn(Input):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=10, max_length=72)
    name: str = Field(default='', max_length=50)
    role: Role = 'operator'


class AccountIn(Input):
    platform: Platform
    appid: str = Field(default='', max_length=100)
    appsecret: str = Field(default='', max_length=200)
    extra: dict = Field(default_factory=dict)
    enabled: bool = True


class OCRConfirmIn(VersionIn):
    data: dict
    confirmed_fields: list[str] = Field(default_factory=list, max_length=200)


class BrowserPublishIn(VersionIn):
    variant_id: int = Field(gt=0)


class GenerateIn(Input):
    scheduled: date | None = None

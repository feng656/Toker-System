from datetime import date, datetime
from pydantic import BaseModel


class LoginIn(BaseModel):
    username: str
    password: str


class MaterialIn(BaseModel):
    category: str
    title: str
    content: str = ""
    biz_line: str = "both"
    publicity: str = "public"
    tags: str = ""
    file_url: str = ""
    enabled: bool = True


class TopicIn(BaseModel):
    biz_line: str
    theme: str
    title: str
    angle: str = ""


class VariantUpdate(BaseModel):
    body: str | None = None
    cover_text: str | None = None
    hashtags: str | None = None


class ReviewIn(BaseModel):
    action: str          # approve / reject
    note: str = ""


class PublishIn(BaseModel):
    published_url: str


class MetricIn(BaseModel):
    variant_id: int
    stat_date: date
    views: int = 0
    likes: int = 0
    comments: int = 0
    collects: int = 0
    shares: int = 0
    new_fans: int = 0
    dm_inquiries: int = 0


class InteractionIn(BaseModel):
    platform: str
    body: str
    kind: str = "comment"
    author_name: str = ""
    author_id: str = ""
    variant_id: int | None = None
    auto_classify: bool = True


class LeadUpdate(BaseModel):
    status: str | None = None
    assignee: str | None = None
    follow_notes: str | None = None


class RuleIn(BaseModel):
    rule_type: str
    pattern: str
    note: str = ""


class UserIn(BaseModel):
    username: str
    password: str
    name: str = ""
    role: str = "operator"

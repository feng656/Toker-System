from datetime import date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="operator")  # admin/operator/sales
    name: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Material(Base):
    __tablename__ = "materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(30))   # 简介/品牌代理/产品明细/案例/资质荣誉/服务能力/FAQ
    biz_line: Mapped[str] = mapped_column(String(10), default="both")  # project/channel/both
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    file_url: Mapped[str] = mapped_column(String(500), default="")
    publicity: Mapped[str] = mapped_column(String(10), default="public")  # public/masked/internal
    tags: Mapped[str] = mapped_column(String(200), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Topic(Base):
    __tablename__ = "topics"
    id: Mapped[int] = mapped_column(primary_key=True)
    biz_line: Mapped[str] = mapped_column(String(10))   # project / channel
    theme: Mapped[str] = mapped_column(String(50))      # 方案科普/案例复盘/工程商痛点/新品到货/招投标知识/公司动态
    title: Mapped[str] = mapped_column(String(200))
    angle: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(10), default="active")  # active/used/archived
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ComplianceRule(Base):
    __tablename__ = "compliance_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_type: Mapped[str] = mapped_column(String(20))  # forbidden/required/ad_law
    pattern: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(String(200), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Content(Base):
    __tablename__ = "contents"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    biz_line: Mapped[str] = mapped_column(String(10), default="project")
    source: Mapped[str] = mapped_column(String(10), default="ai")  # ai/manual
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(15), default="draft")  # draft/approved/rejected/published/archived
    review_note: Mapped[str] = mapped_column(Text, default="")
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    topic: Mapped["Topic"] = relationship()
    variants: Mapped[list["ContentVariant"]] = relationship(
        back_populates="content", cascade="all, delete-orphan"
    )


class ContentVariant(Base):
    __tablename__ = "content_variants"
    id: Mapped[int] = mapped_column(primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("contents.id"))
    platform: Mapped[str] = mapped_column(String(15))  # douyin/shipinhao/gzh/xhs/moments
    body: Mapped[str] = mapped_column(Text, default="")
    cover_text: Mapped[str] = mapped_column(String(200), default="")
    hashtags: Mapped[str] = mapped_column(String(500), default="")
    image_prompt: Mapped[str] = mapped_column(Text, default="")
    best_time: Mapped[str] = mapped_column(String(100), default="")
    assets_url: Mapped[str] = mapped_column(String(500), default="")
    compliance_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    compliance_hits: Mapped[str] = mapped_column(String(500), default="")
    quality_score: Mapped[int] = mapped_column(Integer, default=0)   # AI质检分0-100
    quality_note: Mapped[str] = mapped_column(String(500), default="")  # 质检评语
    confirm_status: Mapped[str] = mapped_column(String(15), default="none")
    # none / pending(待确认) / confirmed(已确认) / rejected(已驳回)
    publish_status: Mapped[str] = mapped_column(String(15), default="none")
    # none / queued / publishing / published / failed
    publish_error: Mapped[str] = mapped_column(String(500), default="")
    published_url: Mapped[str] = mapped_column(String(500), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    content: Mapped[Content] = relationship(back_populates="variants")


class Metric(Base):
    __tablename__ = "metrics"
    __table_args__ = (UniqueConstraint("variant_id", "stat_date"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int] = mapped_column(ForeignKey("content_variants.id"))
    stat_date: Mapped[date] = mapped_column(Date)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    collects: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    new_fans: Mapped[int] = mapped_column(Integer, default=0)
    dm_inquiries: Mapped[int] = mapped_column(Integer, default=0)
    raw_img_url: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Interaction(Base):
    __tablename__ = "interactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    variant_id: Mapped[int | None] = mapped_column(ForeignKey("content_variants.id"), nullable=True)
    platform: Mapped[str] = mapped_column(String(15))
    kind: Mapped[str] = mapped_column(String(10), default="comment")  # comment/dm
    author_name: Mapped[str] = mapped_column(String(100), default="")
    author_id: Mapped[str] = mapped_column(String(100), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    body_img_url: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(primary_key=True)
    interaction_id: Mapped[int | None] = mapped_column(ForeignKey("interactions.id"), nullable=True)
    platform: Mapped[str] = mapped_column(String(15), default="")
    visitor_name: Mapped[str] = mapped_column(String(100), default="")
    intent: Mapped[str] = mapped_column(String(10), default="low")    # high/mid/low/junk
    identity: Mapped[str] = mapped_column(String(10), default="unknown")  # contractor/owner/unknown
    need_summary: Mapped[str] = mapped_column(Text, default="")
    contact_info: Mapped[str] = mapped_column(String(200), default="")
    brand_need: Mapped[str] = mapped_column(String(100), default="")
    reply_suggestion: Mapped[str] = mapped_column(Text, default="")
    assignee: Mapped[str] = mapped_column(String(50), default="")
    status: Mapped[str] = mapped_column(String(15), default="new")
    # new/contacted/wechat_added/opportunity/won/lost
    follow_notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class PlatformAccount(Base):
    """各平台官方API凭据配置，一次性录入。"""
    __tablename__ = "platform_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(15), unique=True)  # gzh/douyin/shipinhao
    appid: Mapped[str] = mapped_column(String(100), default="")
    appsecret: Mapped[str] = mapped_column(String(200), default="")
    access_token: Mapped[str] = mapped_column(String(500), default="")
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class WeeklyReport(Base):
    __tablename__ = "weekly_reports"
    id: Mapped[int] = mapped_column(primary_key=True)
    week_start: Mapped[date] = mapped_column(Date)
    report_md: Mapped[str] = mapped_column(Text, default="")
    insights: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

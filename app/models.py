"""业务模型；公共字段见 db.Record，业务删除为软删除。"""
from datetime import date, datetime
from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey,
                        Index, Integer, JSON, String, Text, UniqueConstraint, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base, Record

J = JSON().with_variant(JSONB, 'postgresql')


class User(Record, Base):
    __tablename__ = 'users'
    __table_args__ = (CheckConstraint("role IN ('admin','operator','sales')", name='user_role'),)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default='operator')
    name: Mapped[str] = mapped_column(String(50), default='')
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Material(Record, Base):
    __tablename__ = 'materials'
    category: Mapped[str] = mapped_column(String(30))
    biz_line: Mapped[str] = mapped_column(String(10), default='both', index=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default='')
    file_url: Mapped[str] = mapped_column(String(500), default='')
    publicity: Mapped[str] = mapped_column(String(10), default='public')
    tags: Mapped[str] = mapped_column(String(200), default='')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Topic(Record, Base):
    __tablename__ = 'topics'
    biz_line: Mapped[str] = mapped_column(String(10), index=True)
    theme: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    angle: Mapped[str] = mapped_column(Text, default='')
    score: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(10), default='active', index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ComplianceRule(Record, Base):
    __tablename__ = 'compliance_rules'
    __table_args__ = (UniqueConstraint('rule_type', 'pattern', name='uq_rule'),)
    rule_type: Mapped[str] = mapped_column(String(20))
    pattern: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(String(200), default='')
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Content(Record, Base):
    __tablename__ = 'contents'
    topic_id: Mapped[int | None] = mapped_column(ForeignKey('topics.id'), nullable=True, index=True)
    biz_line: Mapped[str] = mapped_column(String(10), default='project')
    source: Mapped[str] = mapped_column(String(10), default='ai')
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(15), default='draft')
    review_note: Mapped[str] = mapped_column(Text, default='')
    scheduled_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    generation_key: Mapped[str | None] = mapped_column(String(150), unique=True, nullable=True)
    topic: Mapped['Topic'] = relationship()
    variants: Mapped[list['ContentVariant']] = relationship(back_populates='content')


class ContentVariant(Record, Base):
    __tablename__ = 'content_variants'
    __table_args__ = (
        UniqueConstraint('content_id', 'platform', 'revision', name='uq_variant_revision'),
        Index('uq_variant_current', 'content_id', 'platform', unique=True,
              postgresql_where=text('is_current = true AND deleted_at IS NULL'),
              sqlite_where=text('is_current = 1 AND deleted_at IS NULL')),
        CheckConstraint("status IN ('draft','blocked','pending','published')", name='variant_status'),
    )
    content_id: Mapped[int] = mapped_column(ForeignKey('contents.id'), index=True)
    platform: Mapped[str] = mapped_column(String(15))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey('content_variants.id'), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(15), default='draft', index=True)
    body: Mapped[str] = mapped_column(Text, default='')
    cover_text: Mapped[str] = mapped_column(String(200), default='')
    hashtags: Mapped[str] = mapped_column(String(500), default='')
    image_prompt: Mapped[str] = mapped_column(Text, default='')
    best_time: Mapped[str] = mapped_column(String(100), default='')
    assets_url: Mapped[str] = mapped_column(String(500), default='')
    compliance_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    compliance_hits: Mapped[str] = mapped_column(Text, default='')
    quality_score: Mapped[int] = mapped_column(Integer, default=0)
    quality_note: Mapped[str] = mapped_column(Text, default='')
    confirm_status: Mapped[str] = mapped_column(String(15), default='none')
    rejection_reason: Mapped[str] = mapped_column(Text, default='')
    publish_status: Mapped[str] = mapped_column(String(15), default='none')
    publish_error: Mapped[str] = mapped_column(Text, default='')
    publish_result: Mapped[dict] = mapped_column(J, default=dict)
    published_url: Mapped[str] = mapped_column(String(1000), default='')
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    content: Mapped[Content] = relationship(back_populates='variants')


class ReviewEvent(Record, Base):
    __tablename__ = 'review_events'
    variant_id: Mapped[int] = mapped_column(ForeignKey('content_variants.id'), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text, default='')


class Metric(Record, Base):
    __tablename__ = 'metrics'
    __table_args__ = (UniqueConstraint('variant_id', 'stat_date', name='uq_metric_day'),
                      CheckConstraint('views >= 0 AND likes >= 0 AND comments >= 0 AND collects >= 0 AND shares >= 0 AND new_fans >= 0 AND dm_inquiries >= 0', name='metric_nonnegative'))
    variant_id: Mapped[int] = mapped_column(ForeignKey('content_variants.id'), index=True)
    stat_date: Mapped[date] = mapped_column(Date, index=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    collects: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    new_fans: Mapped[int] = mapped_column(Integer, default=0)
    dm_inquiries: Mapped[int] = mapped_column(Integer, default=0)
    raw_img_url: Mapped[str] = mapped_column(String(500), default='')
    source: Mapped[str] = mapped_column(String(20), default='manual')
    ocr_task_id: Mapped[int | None] = mapped_column(ForeignKey('ocr_tasks.id'), nullable=True)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)


class OCRTask(Record, Base):
    __tablename__ = 'ocr_tasks'
    request_key: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(15))
    variant_id: Mapped[int | None] = mapped_column(ForeignKey('content_variants.id'), nullable=True)
    platform: Mapped[str] = mapped_column(String(15), default='')
    status: Mapped[str] = mapped_column(String(20), default='pending_review', index=True)
    image_url: Mapped[str] = mapped_column(String(500))
    raw_text: Mapped[str] = mapped_column(Text, default='')
    fields: Mapped[dict] = mapped_column(J, default=dict)
    confidence: Mapped[dict] = mapped_column(J, default=dict)
    low_confidence_fields: Mapped[list] = mapped_column(J, default=list)
    error: Mapped[str] = mapped_column(Text, default='')
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey('users.id'), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_payload: Mapped[dict] = mapped_column(J, default=dict)
    result: Mapped[dict] = mapped_column(J, default=dict)


class Interaction(Record, Base):
    __tablename__ = 'interactions'
    variant_id: Mapped[int | None] = mapped_column(ForeignKey('content_variants.id'), nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(15), index=True)
    kind: Mapped[str] = mapped_column(String(10), default='comment')
    author_name: Mapped[str] = mapped_column(String(100), default='')
    author_id: Mapped[str] = mapped_column(String(100), default='')
    body: Mapped[str] = mapped_column(Text, default='')
    body_img_url: Mapped[str] = mapped_column(String(500), default='')
    source_key: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    ocr_task_id: Mapped[int | None] = mapped_column(ForeignKey('ocr_tasks.id'), nullable=True)
    classify_status: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    classify_error: Mapped[str] = mapped_column(Text, default='')


class Lead(Record, Base):
    __tablename__ = 'leads'
    __table_args__ = (CheckConstraint("status IN ('new','contacted','opportunity','won','lost','invalid')", name='lead_status'),)
    interaction_id: Mapped[int | None] = mapped_column(ForeignKey('interactions.id'), nullable=True)
    platform: Mapped[str] = mapped_column(String(15), default='')
    visitor_name: Mapped[str] = mapped_column(String(100), default='')
    author_key: Mapped[str] = mapped_column(String(200), default='', index=True)
    intent: Mapped[str] = mapped_column(String(10), default='low', index=True)
    identity: Mapped[str] = mapped_column(String(15), default='unknown')
    need_summary: Mapped[str] = mapped_column(Text, default='')
    contact_info: Mapped[str] = mapped_column(String(300), default='')
    contact_keys: Mapped[list] = mapped_column(J, default=list)
    brand_need: Mapped[str] = mapped_column(String(100), default='')
    reply_suggestion: Mapped[str] = mapped_column(Text, default='')
    assignee: Mapped[str] = mapped_column(String(50), default='', index=True)
    status: Mapped[str] = mapped_column(String(15), default='new', index=True)
    follow_notes: Mapped[str] = mapped_column(Text, default='')
    repeat: Mapped[bool] = mapped_column(Boolean, default=False)
    repeat_count: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)


class LeadSource(Record, Base):
    __tablename__ = 'lead_sources'
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'), index=True)
    interaction_id: Mapped[int] = mapped_column(ForeignKey('interactions.id'), unique=True)
    match_reason: Mapped[str] = mapped_column(String(30), default='new')
    extracted: Mapped[dict] = mapped_column(J, default=dict)


class LeadFollowup(Record, Base):
    __tablename__ = 'lead_followups'
    lead_id: Mapped[int] = mapped_column(ForeignKey('leads.id'), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    old_status: Mapped[str] = mapped_column(String(15))
    new_status: Mapped[str] = mapped_column(String(15))
    note: Mapped[str] = mapped_column(Text, default='')


class Outbox(Record, Base):
    __tablename__ = 'outbox'
    __table_args__ = (CheckConstraint("status IN ('pending','sent','failed','dead')", name='outbox_status'),
                      Index('ix_outbox_due', 'status', 'next_attempt_at'))
    event_key: Mapped[str] = mapped_column(String(200), unique=True)
    channel: Mapped[str] = mapped_column(String(20))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey('leads.id'), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(J, default=dict)
    status: Mapped[str] = mapped_column(String(10), default='pending')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default='')
    response: Mapped[dict] = mapped_column(J, default=dict)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AIJob(Record, Base):
    __tablename__ = 'ai_jobs'
    kind: Mapped[str] = mapped_column(String(30), index=True)
    resource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='running', index=True)
    provider: Mapped[str] = mapped_column(String(100), default='')
    model: Mapped[str] = mapped_column(String(100), default='')
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    input_hash: Mapped[str] = mapped_column(String(64))
    output: Mapped[dict] = mapped_column(J, default=dict)
    error: Mapped[str] = mapped_column(Text, default='')
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)


class TaskExecution(Record, Base):
    __tablename__ = 'task_executions'
    task_key: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(J, default=dict)
    result: Mapped[dict] = mapped_column(J, default=dict)
    error: Mapped[str] = mapped_column(Text, default='')
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PlatformAccount(Record, Base):
    __tablename__ = 'platform_accounts'
    platform: Mapped[str] = mapped_column(String(15), unique=True)
    appid: Mapped[str] = mapped_column(String(100), default='')
    appsecret: Mapped[str] = mapped_column(String(200), default='')
    access_token: Mapped[str] = mapped_column(String(500), default='')
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    extra: Mapped[dict] = mapped_column(J, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class WeeklyReport(Record, Base):
    __tablename__ = 'weekly_reports'
    week_start: Mapped[date] = mapped_column(Date, unique=True)
    report_md: Mapped[str] = mapped_column(Text, default='')
    insights: Mapped[dict] = mapped_column(J, default=dict)

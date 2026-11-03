"""内容生产和合规：生成、审核、版本历史与真实发布回填。"""
import json
import unicodedata
from datetime import date, timedelta
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import utcnow
from .llm import AIUnavailable, call_json
from .models import ComplianceRule, Content, ContentVariant, Material, ReviewEvent, Topic
from .schemas import valid_publish_url

PLATFORMS = ['douyin', 'shipinhao', 'gzh', 'moments']
SYS = '''你是自由光科技B2B内容策划。project面向政企甲方；channel面向工程商。
只使用给定公开素材，不虚构业绩、不泄露客户/底价。遵守禁用词和必需口径。
返回JSON，四个平台douyin/shipinhao/gzh/moments各含body、cover_text、hashtags、image_prompt、best_time。
抖音是60秒口播，视频号沉稳行业分享，公众号深度结构化图文，朋友圈3-5行。'''


def normalize(text):
    return ''.join(unicodedata.normalize('NFKC', text).casefold().split())


def check_compliance(db: Session, text: str):
    rules = db.scalars(select(ComplianceRule).where(ComplianceRule.enabled.is_(True))).all()
    normalized = normalize(text)
    hits = []
    if not normalized:
        hits.append('empty:正文不能为空')
    for r in rules:
        present = normalize(r.pattern) in normalized
        if (r.rule_type in ('forbidden', 'ad_law') and present) or (r.rule_type == 'required' and not present):
            hits.append(f'{r.rule_type}:{r.pattern}')
    return not hits, hits


def variant_text(v):
    return '\n'.join([v.body or '', v.cover_text or '', v.hashtags or ''])


def apply_compliance(db, v):
    v.compliance_ok, hits = check_compliance(db, variant_text(v))
    v.compliance_hits = ','.join(hits)
    if not v.compliance_ok:
        v.status = 'blocked'
        v.confirm_status = 'none'
    return v.compliance_ok


def pick_topics(db, n_per_line=1):
    result = []
    for line in ('project', 'channel'):
        result.extend(db.scalars(select(Topic).where(Topic.biz_line == line, Topic.status == 'active')
                      .order_by(Topic.score.desc(), Topic.last_used_at.asc().nulls_first(), Topic.id)
                      .limit(n_per_line)).all())
    return result


def generation_context(db, topic):
    # masked 尚未经过专门脱敏审批，不能把原文直接发送AI。
    mats = db.scalars(select(Material).where(Material.enabled.is_(True), Material.publicity == 'public',
                   Material.biz_line.in_([topic.biz_line, 'both'])).limit(40)).all()
    rules = db.scalars(select(ComplianceRule).where(ComplianceRule.enabled.is_(True))).all()
    context = {'title': topic.title, 'angle': topic.angle, 'biz_line': topic.biz_line,
               'materials': [{'title': m.title, 'content': m.content[:1000]} for m in mats],
               'rules': [{'type': r.rule_type, 'pattern': r.pattern} for r in rules],
               'required': [r.pattern for r in rules if r.rule_type == 'required']}
    return context


def build_variant(db, c, platform, data, revision=1, parent_id=None):
    if not isinstance(data, dict) or not str(data.get('body', '')).strip():
        raise AIUnavailable(f'{platform}生成结果缺少正文')
    v = ContentVariant(content_id=c.id, platform=platform, body=str(data['body'])[:30000],
                       cover_text=str(data.get('cover_text', ''))[:200],
                       hashtags=str(data.get('hashtags', ''))[:500],
                       image_prompt=str(data.get('image_prompt', '')),
                       best_time=str(data.get('best_time', ''))[:100], revision=revision, parent_id=parent_id)
    db.add(v)
    db.flush()
    from .quality import score_variant
    score_variant(db, v, c.title)
    return v


def generate_daily(db: Session, target: date | None = None, topics=None):
    target = target or date.today() + timedelta(days=1)
    topics = topics or pick_topics(db)
    if len(topics) < 2:
        raise ValueError('需至少一个甲方线和一个渠道线的启用选题')
    created = []
    for topic in topics:
        key = f'daily:{target}:{topic.id}'
        existing = db.scalar(select(Content).where(Content.generation_key == key))
        if existing:
            created.append(existing)
            continue
        context = generation_context(db, topic)
        data = call_json(db, 'generate', SYS, json.dumps(context, ensure_ascii=False),
                         topic.id, context)
        # 先校验整份输出，禁止只生成部分平台后留下半包。
        if any(not isinstance(data.get(p), dict) or not data[p].get('body') for p in PLATFORMS):
            raise AIUnavailable('AI未返回四个平台的完整正文')
        c = Content(topic_id=topic.id, biz_line=topic.biz_line, title=topic.title,
                    scheduled_date=target, generation_key=key, status='draft')
        db.add(c)
        db.flush()
        for p in PLATFORMS:
            build_variant(db, c, p, data[p])
        topic.last_used_at = utcnow()
        db.flush()
        created.append(c)
    return created


def ensure_current(v):
    if not v.is_current or v.confirm_status == 'rejected':
        raise HTTPException(409, '历史或驳回版本不能修改、审核或发布')


def approve_variant(db, v, actor):
    ensure_current(v)
    if v.status == 'published':
        raise HTTPException(409, '已发布内容不能重复审核')
    if not apply_compliance(db, v):
        db.commit()  # 即使拦截也必须保存真实blocked状态。
        raise HTTPException(409, '命中合规红线，不能人工绕过：' + v.compliance_hits)
    if v.status != 'pending' or v.quality_score < 70:
        raise HTTPException(409, '内容尚未通过质检；修改后请先重新质检')
    v.confirm_status = 'confirmed'
    db.add(ReviewEvent(variant_id=v.id, actor_id=actor.id, action='approve'))
    return v


def reject_variant(db, v, reason, actor):
    ensure_current(v)
    if v.status == 'published':
        raise HTTPException(409, '已发布内容不能驳回')
    v.confirm_status = 'rejected'
    v.rejection_reason = reason
    v.is_current = False
    db.add(ReviewEvent(variant_id=v.id, actor_id=actor.id, action='reject', reason=reason))
    db.flush()
    return regenerate_variant(db, v)


def regenerate_variant(db, old):
    from .tasks import lock
    lock(db, f'regenerate:{old.id}')
    existing = db.scalar(select(ContentVariant).where(ContentVariant.parent_id == old.id))
    if existing:
        return existing
    topic = old.content.topic
    context = generation_context(db, topic) if topic else {'title': old.content.title, 'required': []}
    context.update(platform=old.platform, reason=old.rejection_reason, previous=old.body)
    try:
        data = call_json(db, 'regenerate', SYS + '\n只输出给定platform的一个版本对象，按reason改写。',
                         json.dumps(context, ensure_ascii=False), old.id, context)
        if not isinstance(data, dict) or not str(data.get('body', '')).strip():
            raise AIUnavailable('重生成结果缺少正文，保留驳回原因待重试')
    except AIUnavailable as exc:
        old.quality_note = '重生成失败，可重试：' + str(exc)
        return None
    new = build_variant(db, old.content, old.platform, data, old.revision + 1, old.id)
    old.quality_note = '已驳回并生成新版本'
    return new


def refresh_content_status(db, content):
    rows = db.scalars(select(ContentVariant).where(ContentVariant.content_id == content.id,
                      ContentVariant.is_current.is_(True))).all()
    content.status = 'published' if rows and all(v.status == 'published' and v.published_url for v in rows) else 'approved' if any(v.confirm_status == 'confirmed' for v in rows) else 'draft'


def record_publication(db, v, url):
    ensure_current(v)
    url = valid_publish_url(url)
    if v.status == 'published':
        if v.published_url == url:
            return v
        raise HTTPException(409, '已发布链接不能直接覆盖')
    if v.confirm_status != 'confirmed':
        raise HTTPException(409, '须先人工审核通过')
    if not apply_compliance(db, v):
        db.commit()
        raise HTTPException(409, '合规规则已变更，禁止发布')
    v.status, v.publish_status = 'published', 'published'
    v.published_url, v.published_at = url, utcnow()
    v.publish_error = ''
    db.flush()
    refresh_content_status(db, v.content)
    return v

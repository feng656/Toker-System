"""一期后端接口；规范前缀由 main 注册为 /api/v1。"""
from datetime import date, timedelta
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from . import config, storage
from .auth import current_user, hash_password, make_token, require_role, verify_password
from .db import get_db, utcnow
from .models import (AIJob, ComplianceRule, Content, ContentVariant, Interaction, Lead,
    LeadFollowup, LeadSource, Material, Metric, OCRTask, Outbox, PlatformAccount,
    ReviewEvent, TaskExecution, Topic, User, WeeklyReport)
from .schemas import (AccountIn, BrowserPublishIn, InteractionIn, LeadUpdate, LoginIn,
    MaterialIn, MetricIn, OCRConfirmIn, PasswordIn, PublishIn, RejectIn, ReviewIn,
    RuleIn, TopicIn, UserIn, VariantUpdate, VersionIn)

api = APIRouter()
operate = require_role('admin', 'operator')
admin = require_role('admin')


def row(db, model, key, expected=None):
    obj = db.get(model, key)
    if obj is None or obj.deleted_at:
        raise HTTPException(404, '记录不存在')
    if expected is not None and obj.version != expected:
        raise HTTPException(409, '数据已被修改，请刷新后重试')
    return obj


def as_dict(obj, exclude=()):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns
            if c.name not in {'deleted_at', *exclude}}


def variant_dict(v):
    return as_dict(v)


def content_dict(c):
    result = as_dict(c)
    result['topic'] = c.topic.title if c.topic else None
    result['variants'] = [variant_dict(v) for v in c.variants if not v.deleted_at]
    return result


def lead_scope(query, user):
    return query.where(Lead.assignee == user.username) if user.role == 'sales' else query


def visible_lead(db, key, user, expected=None):
    lead = row(db, Lead, key, expected)
    if user.role == 'sales' and lead.assignee != user.username:
        raise HTTPException(404, '线索不存在或未指派给你')
    return lead


@api.post('/auth/login', tags=['认证'])
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username, User.enabled.is_(True)))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, '账号或密码错误')
    return {'token': make_token(user), 'token_type': 'bearer',
            'user': as_dict(user, {'password_hash', 'token_version'})}


@api.get('/auth/me', tags=['认证'])
def me(user: User = Depends(current_user)):
    return as_dict(user, {'password_hash', 'token_version'})


@api.post('/auth/password', tags=['认证'])
def password(body: PasswordIn, db: Session = Depends(get_db), user=Depends(current_user)):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(400, '原密码错误')
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    db.commit()
    return {'ok': True, 'note': '密码已修改，旧令牌全部失效，请重新登录'}


@api.get('/users', tags=['权限'])
def users(db: Session = Depends(get_db), user=Depends(operate)):
    q = select(User)
    if user.role != 'admin':
        q = q.where(User.role == 'sales', User.enabled.is_(True))
    return [as_dict(x, {'password_hash', 'token_version'}) for x in db.scalars(q).all()]


@api.post('/users', status_code=201, tags=['权限'])
def create_user(body: UserIn, db: Session = Depends(get_db), _=Depends(admin)):
    if db.scalar(select(User).where(User.username == body.username).execution_options(include_deleted=True)):
        raise HTTPException(409, '用户名已存在')
    user = User(**body.model_dump(exclude={'password'}), password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    return as_dict(user, {'password_hash', 'token_version'})


@api.post('/users/{uid}/disable', tags=['权限'])
def disable_user(uid: int, db: Session = Depends(get_db), actor=Depends(admin)):
    user = row(db, User, uid)
    if uid == actor.id:
        raise HTTPException(409, '不能停用自己')
    user.enabled, user.token_version = False, user.token_version + 1
    db.commit()
    return {'ok': True}


@api.get('/materials', tags=['素材'])
def materials(category: str | None = None, biz_line: str | None = None,
              publicity: str | None = None, enabled: bool | None = None,
              limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
              db: Session = Depends(get_db), _=Depends(operate)):
    q = select(Material).order_by(Material.id)
    if category:
        q = q.where(Material.category == category)
    if biz_line:
        q = q.where(Material.biz_line.in_([biz_line, 'both']))
    if publicity:
        q = q.where(Material.publicity == publicity)
    if enabled is not None:
        q = q.where(Material.enabled == enabled)
    return [as_dict(x) for x in db.scalars(q.limit(limit).offset(offset)).all()]


@api.post('/materials', status_code=201, tags=['素材'])
def create_material(body: MaterialIn, db: Session = Depends(get_db), _=Depends(operate)):
    obj = Material(**body.model_dump(exclude={'expected_version'}))
    db.add(obj)
    db.commit()
    return as_dict(obj)


@api.put('/materials/{mid}', tags=['素材'])
def update_material(mid: int, body: MaterialIn, db: Session = Depends(get_db), _=Depends(operate)):
    obj = row(db, Material, mid, body.expected_version)
    for k, value in body.model_dump(exclude={'expected_version'}).items():
        setattr(obj, k, value)
    db.commit()
    return as_dict(obj)


@api.delete('/materials/{mid}', tags=['素材'])
def delete_material(mid: int, db: Session = Depends(get_db), _=Depends(admin)):
    obj = row(db, Material, mid)
    obj.deleted_at = utcnow()
    db.commit()
    return {'ok': True, 'soft_deleted': True}


@api.post('/materials/{mid}/file', tags=['素材'])
def upload_material(mid: int, f: UploadFile = File(...), db: Session = Depends(get_db), _=Depends(operate)):
    obj = row(db, Material, mid)
    data = f.file.read(config.UPLOAD_MAX_BYTES + 1)
    if not data or len(data) > config.UPLOAD_MAX_BYTES:
        raise HTTPException(413, '文件为空或超过限制')
    try:
        obj.file_url = storage.put(data, f.filename or 'file', f.content_type or 'application/octet-stream')
    except Exception:
        raise HTTPException(503, '对象存储不可用，文件未保存')
    db.commit()
    return {'file_url': obj.file_url}


@api.get('/materials/{mid}/file', tags=['素材'])
def download_material(mid: int, db: Session = Depends(get_db), _=Depends(operate)):
    obj = row(db, Material, mid)
    if not obj.file_url:
        raise HTTPException(404, '没有关联文件')
    return {'url': storage.signed_url(obj.file_url), 'expires_seconds': 600}


@api.get('/topics', tags=['选题'])
def topics(biz_line: str | None = None, status: str = 'active', db: Session = Depends(get_db), _=Depends(operate)):
    q = select(Topic).where(Topic.status == status).order_by(Topic.score.desc(), Topic.id)
    if biz_line:
        q = q.where(Topic.biz_line == biz_line)
    return [as_dict(x) for x in db.scalars(q.limit(500)).all()]


@api.post('/topics', status_code=201, tags=['选题'])
def create_topic(body: TopicIn, db: Session = Depends(get_db), _=Depends(operate)):
    obj = Topic(**body.model_dump())
    db.add(obj)
    db.commit()
    return as_dict(obj)


@api.put('/topics/{tid}/status', tags=['选题'])
def topic_status(tid: int, status: Literal['active', 'used', 'archived'], expected_version: int | None = None,
                 db: Session = Depends(get_db), _=Depends(operate)):
    obj = row(db, Topic, tid, expected_version)
    obj.status = status
    db.commit()
    return as_dict(obj)


@api.get('/rules', tags=['合规'])
def rules(db: Session = Depends(get_db), _=Depends(operate)):
    return [as_dict(x) for x in db.scalars(select(ComplianceRule).order_by(ComplianceRule.id)).all()]


@api.post('/rules', status_code=201, tags=['合规'])
def create_rule(body: RuleIn, db: Session = Depends(get_db), _=Depends(admin)):
    obj = ComplianceRule(**body.model_dump())
    db.add(obj)
    db.commit()
    return as_dict(obj)


@api.delete('/rules/{rid}', tags=['合规'])
def delete_rule(rid: int, db: Session = Depends(get_db), _=Depends(admin)):
    obj = row(db, ComplianceRule, rid)
    obj.deleted_at = utcnow()
    obj.enabled = False
    db.commit()
    return {'ok': True, 'soft_deleted': True}


def run_daily_task(key):
    from .db import SessionLocal
    from .tasks import execute_daily
    with SessionLocal() as db:
        job = db.get(TaskExecution, key)
        if job:
            execute_daily(db, job)


@api.post('/generate/daily', status_code=202, tags=['内容任务'])
def generate(bg: BackgroundTasks, scheduled: date | None = None, db: Session = Depends(get_db), _=Depends(operate)):
    from .tasks import enqueue_daily
    try:
        job = enqueue_daily(db, scheduled)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    db.commit()
    if job.status == 'pending':
        bg.add_task(run_daily_task, job.id)
    return {'ok': True, 'task_id': job.id, 'status': job.status, 'state_url': f'/api/v1/tasks/{job.id}'}


@api.get('/generate/status', tags=['内容任务'])
def generate_status(db: Session = Depends(get_db), _=Depends(operate)):
    job = db.scalar(select(TaskExecution).where(TaskExecution.kind == 'daily_generate').order_by(TaskExecution.id.desc()))
    return {'running': bool(job and job.status in ('pending', 'running')), 'last': as_dict(job) if job else None}


@api.get('/tasks', tags=['内容任务'])
def tasks(db: Session = Depends(get_db), _=Depends(operate)):
    return [as_dict(x) for x in db.scalars(select(TaskExecution).order_by(TaskExecution.id.desc()).limit(100)).all()]


@api.get('/tasks/{tid}', tags=['内容任务'])
def task(tid: int, db: Session = Depends(get_db), _=Depends(operate)):
    return as_dict(row(db, TaskExecution, tid))


@api.post('/tasks/{tid}/retry', status_code=202, tags=['内容任务'])
def retry_task(tid: int, bg: BackgroundTasks, db: Session = Depends(get_db), _=Depends(operate)):
    job = row(db, TaskExecution, tid)
    if job.status not in ('failed', 'pending'):
        raise HTTPException(409, '仅失败或待执行的任务可重试')
    job.status = 'pending'
    db.commit()
    bg.add_task(run_daily_task, job.id)
    return as_dict(job)


@api.get('/ai-jobs', tags=['AI审计'])
def ai_jobs(kind: str | None = None, status: str | None = None, limit: int = Query(100, ge=1, le=500),
            db: Session = Depends(get_db), _=Depends(operate)):
    q = select(AIJob).order_by(AIJob.id.desc())
    if kind:
        q = q.where(AIJob.kind == kind)
    if status:
        q = q.where(AIJob.status == status)
    return [as_dict(x) for x in db.scalars(q.limit(limit)).all()]


@api.get('/llm/status', tags=['AI审计'])
def llm_status(_=Depends(operate)):
    from .llm import status
    return status()


@api.get('/contents', tags=['内容'])
def contents(status: str | None = None, scheduled: date | None = None,
             limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), _=Depends(operate)):
    q = select(Content).options(selectinload(Content.variants), selectinload(Content.topic)).order_by(Content.id.desc())
    if status:
        q = q.where(Content.status == status)
    if scheduled:
        q = q.where(Content.scheduled_date == scheduled)
    return [content_dict(c) for c in db.scalars(q.limit(limit)).all()]


@api.get('/contents/{cid}', tags=['内容'])
def content(cid: int, db: Session = Depends(get_db), _=Depends(operate)):
    return content_dict(row(db, Content, cid))


@api.get('/variants/{vid}/history', tags=['审核'])
def variant_history(vid: int, db: Session = Depends(get_db), _=Depends(operate)):
    v = row(db, ContentVariant, vid)
    return [variant_dict(x) for x in db.scalars(select(ContentVariant).where(
        ContentVariant.content_id == v.content_id, ContentVariant.platform == v.platform)
        .order_by(ContentVariant.revision)).all()]


@api.put('/variants/{vid}', tags=['内容'])
def update_variant(vid: int, body: VariantUpdate, db: Session = Depends(get_db), _=Depends(operate)):
    from .generator import apply_compliance, ensure_current
    v = row(db, ContentVariant, vid, body.expected_version)
    ensure_current(v)
    if v.status == 'published':
        raise HTTPException(409, '已发布版本不能修改正文')
    for k, value in body.model_dump(exclude={'expected_version'}, exclude_none=True).items():
        setattr(v, k, value)
    v.status, v.confirm_status, v.quality_score = 'draft', 'none', 0
    v.quality_note = '文案已变更，请重新质检和审核'
    apply_compliance(db, v)
    db.commit()
    return variant_dict(v)


@api.post('/variants/{vid}/quality', tags=['审核'])
def quality(vid: int, body: VersionIn, db: Session = Depends(get_db), _=Depends(operate)):
    from .generator import ensure_current
    from .quality import score_variant
    v = row(db, ContentVariant, vid, body.expected_version)
    ensure_current(v)
    if v.status == 'published':
        raise HTTPException(409, '已发布版本不能重新质检')
    score_variant(db, v, v.content.title)
    db.commit()
    return variant_dict(v)


@api.post('/variants/{vid}/approve', tags=['审核'])
@api.post('/variants/{vid}/confirm', include_in_schema=False)
def approve(vid: int, body: VersionIn = VersionIn(), db: Session = Depends(get_db), user=Depends(operate)):
    from .generator import approve_variant, refresh_content_status
    v = row(db, ContentVariant, vid, body.expected_version)
    approve_variant(db, v, user)
    db.flush()
    refresh_content_status(db, v.content)
    db.commit()
    return variant_dict(v)


@api.post('/variants/{vid}/reject', tags=['审核'])
@api.post('/variants/{vid}/confirm-reject', include_in_schema=False)
def reject(vid: int, body: RejectIn, db: Session = Depends(get_db), user=Depends(operate)):
    from .generator import reject_variant
    v = row(db, ContentVariant, vid, body.expected_version)
    new = reject_variant(db, v, body.reason, user)
    db.commit()
    return {'rejected': variant_dict(v), 'new_variant': variant_dict(new) if new else None,
            'retry_url': f'/api/v1/variants/{vid}/regenerate' if not new else None}


@api.post('/variants/{vid}/regenerate', tags=['审核'])
def regenerate(vid: int, db: Session = Depends(get_db), _=Depends(operate)):
    from .generator import regenerate_variant
    v = row(db, ContentVariant, vid)
    if v.confirm_status != 'rejected' or not v.rejection_reason:
        raise HTTPException(409, '仅可重试有理由的驳回版本')
    new = regenerate_variant(db, v)
    db.commit()
    return {'new_variant': variant_dict(new) if new else None, 'error': v.quality_note if not new else ''}


@api.post('/contents/{cid}/review', tags=['审核'])
def content_review(cid: int, body: ReviewIn, db: Session = Depends(get_db), user=Depends(operate)):
    from .generator import approve_variant, reject_variant, refresh_content_status
    c = row(db, Content, cid)
    current = [v for v in c.variants if v.is_current and v.status != 'published']
    if body.action == 'approve':
        # 先预检所有版本，不允许批量接口绕过blocked或部分成功。
        from .generator import apply_compliance
        if any(not apply_compliance(db, v) or v.status != 'pending' for v in current):
            db.commit()
            raise HTTPException(409, '存在未通过合规/质检版本，请单条处理')
        for v in current:
            approve_variant(db, v, user)
    else:
        if not body.note.strip():
            raise HTTPException(422, '驳回必须填写理由')
        for v in current:
            reject_variant(db, v, body.note, user)
        c.review_note = body.note
    db.flush()
    refresh_content_status(db, c)
    db.commit()
    return content_dict(c)


@api.get('/confirm/pending', tags=['审核'])
def pending(db: Session = Depends(get_db), _=Depends(operate)):
    rows = db.scalars(select(ContentVariant).where(ContentVariant.is_current.is_(True),
        ContentVariant.status == 'pending', ContentVariant.confirm_status == 'pending')).all()
    return [{**variant_dict(v), 'content_title': v.content.title, 'biz_line': v.content.biz_line} for v in rows]


@api.post('/variants/{vid}/publish', tags=['发布'])
def publish(vid: int, body: PublishIn, db: Session = Depends(get_db), _=Depends(operate)):
    from .generator import record_publication
    v = row(db, ContentVariant, vid, body.expected_version)
    record_publication(db, v, body.published_url)
    db.commit()
    return variant_dict(v)


@api.post('/variants/{vid}/publish/official', tags=['发布'])
def official_publish(vid: int, db: Session = Depends(get_db), _=Depends(operate)):
    from .publisher import publish_variant
    v = row(db, ContentVariant, vid)
    result = publish_variant(db, v)
    return {**variant_dict(v), 'publish_result': result}


@api.get('/todo/today', tags=['发布'])
def todo(scheduled: date | None = None, db: Session = Depends(get_db), _=Depends(operate)):
    target = scheduled or date.today()
    rows = db.scalars(select(ContentVariant).join(Content).where(Content.scheduled_date <= target,
        ContentVariant.is_current.is_(True), ContentVariant.status == 'pending',
        ContentVariant.confirm_status == 'confirmed', ContentVariant.published_url == '')
        .order_by(Content.scheduled_date, ContentVariant.id)).all()
    return {'date': str(target), 'pending': [{**variant_dict(v), 'content_title': v.content.title,
                      'content_id': v.content_id, 'biz_line': v.content.biz_line} for v in rows]}


@api.get('/browser/{platform}/open', tags=['实验发布适配'])
async def browser_open(platform: str, _=Depends(operate)):
    from .browser_agent import open_platform
    return await open_platform(platform)


@api.get('/browser/{platform}/screenshot', tags=['实验发布适配'])
async def browser_screenshot(platform: str, _=Depends(operate)):
    from .browser_agent import screenshot
    return await screenshot(platform)


@api.post('/browser/{platform}/publish', tags=['实验发布适配'])
async def browser_publish(platform: str, body: BrowserPublishIn, db: Session = Depends(get_db), _=Depends(operate)):
    from .browser_agent import fill_variant
    v = row(db, ContentVariant, body.variant_id, body.expected_version)
    if platform != v.platform:
        raise HTTPException(422, '平台与版本不一致')
    return await fill_variant(db, v)


@api.get('/accounts/status', tags=['设置'])
def accounts_status(db: Session = Depends(get_db), _=Depends(operate)):
    rows = {a.platform: a for a in db.scalars(select(PlatformAccount)).all()}
    return [{'platform': p, 'configured': bool(rows.get(p) and rows[p].appid),
             'auto': bool(config.OFFICIAL_PUBLISH_ENABLED and rows.get(p) and rows[p].enabled),
             'mode': 'experimental' if config.OFFICIAL_PUBLISH_ENABLED else 'manual'}
            for p in ('douyin', 'shipinhao', 'gzh', 'moments', 'xhs')]


@api.get('/accounts', tags=['设置'])
def accounts(db: Session = Depends(get_db), _=Depends(admin)):
    return [as_dict(x, {'appsecret', 'access_token'}) for x in db.scalars(select(PlatformAccount)).all()]


@api.post('/accounts', tags=['设置'])
def set_account(body: AccountIn, db: Session = Depends(get_db), _=Depends(admin)):
    obj = db.scalar(select(PlatformAccount).where(PlatformAccount.platform == body.platform))
    if not obj:
        obj = PlatformAccount(platform=body.platform)
        db.add(obj)
    for k, value in body.model_dump().items():
        if k == 'appsecret' and not value:
            continue
        setattr(obj, k, value)
    db.commit()
    return as_dict(obj, {'appsecret', 'access_token'})


@api.get('/metrics', tags=['指标'])
def metrics(variant_id: int | None = None, start: date | None = None, end: date | None = None,
            db: Session = Depends(get_db), _=Depends(operate)):
    q = select(Metric).order_by(Metric.stat_date.desc(), Metric.id)
    if variant_id:
        q = q.where(Metric.variant_id == variant_id)
    if start:
        q = q.where(Metric.stat_date >= start)
    if end:
        q = q.where(Metric.stat_date <= end)
    return [as_dict(x) for x in db.scalars(q.limit(500)).all()]


@api.post('/metrics', tags=['指标'])
def add_metric(body: MetricIn, db: Session = Depends(get_db), user=Depends(operate)):
    from .ocr import save_metric
    obj = save_metric(db, body, user.id)
    db.commit()
    return as_dict(obj)


@api.post('/upload/screenshot', tags=['OCR'])
def upload_screenshot(kind: str = Form(...), variant_id: int | None = Form(None), platform: str = Form(''),
                      f: UploadFile = File(...), idempotency_key: str | None = Header(None),
                      db: Session = Depends(get_db), _=Depends(operate)):
    from .ocr import create_task
    data = f.file.read(config.UPLOAD_MAX_BYTES + 1)
    task = create_task(db, data, f.filename or 'screenshot.png', kind, variant_id, platform, idempotency_key)
    db.commit()
    return as_dict(task)


@api.get('/ocr/tasks', tags=['OCR'])
def ocr_tasks(status: str | None = None, db: Session = Depends(get_db), _=Depends(operate)):
    q = select(OCRTask).order_by(OCRTask.id.desc())
    if status:
        q = q.where(OCRTask.status == status)
    return [as_dict(x) for x in db.scalars(q.limit(200)).all()]


@api.get('/ocr/tasks/{tid}', tags=['OCR'])
def ocr_task(tid: int, db: Session = Depends(get_db), _=Depends(operate)):
    return as_dict(row(db, OCRTask, tid))


@api.get('/ocr/tasks/{tid}/image', tags=['OCR'])
def ocr_image(tid: int, db: Session = Depends(get_db), _=Depends(operate)):
    task = row(db, OCRTask, tid)
    return {'url': storage.signed_url(task.image_url), 'expires_seconds': 600}


@api.post('/ocr/tasks/{tid}/retry', tags=['OCR'])
def retry_ocr(tid: int, db: Session = Depends(get_db), _=Depends(operate)):
    from .ocr import apply_recognition
    obj = row(db, OCRTask, tid)
    if obj.status == 'confirmed':
        raise HTTPException(409, '已确认截图不能重新识别')
    try:
        data = storage.get(obj.image_url)
    except Exception:
        raise HTTPException(503, '无法读取已存截图')
    apply_recognition(obj, data)
    obj.attempts += 1
    db.commit()
    return as_dict(obj)


@api.post('/ocr/tasks/{tid}/confirm', tags=['OCR'])
def confirm_ocr(tid: int, body: OCRConfirmIn, db: Session = Depends(get_db), user=Depends(operate)):
    from .ocr import confirm_task
    obj = row(db, OCRTask, tid, body.expected_version)
    confirm_task(db, obj, body, user)
    db.commit()
    return as_dict(obj)


@api.get('/interactions', tags=['互动线索'])
def interactions(platform: str | None = None, variant_id: int | None = None, status: str | None = None,
                 limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db), _=Depends(operate)):
    q = select(Interaction).order_by(Interaction.id.desc())
    if platform:
        q = q.where(Interaction.platform == platform)
    if variant_id:
        q = q.where(Interaction.variant_id == variant_id)
    if status:
        q = q.where(Interaction.classify_status == status)
    return [as_dict(x) for x in db.scalars(q.limit(limit)).all()]


@api.post('/interactions', status_code=201, tags=['互动线索'])
def add_interaction(body: InteractionIn, db: Session = Depends(get_db), _=Depends(operate)):
    from .classifier import classify_interaction
    from .tasks import lock
    if body.variant_id:
        row(db, ContentVariant, body.variant_id)
    if body.source_key:
        lock(db, f'interaction:{body.source_key}')
        old = db.scalar(select(Interaction).where(Interaction.source_key == body.source_key))
        if old:
            src = db.scalar(select(LeadSource).where(LeadSource.interaction_id == old.id))
            return {'interaction_id': old.id, 'lead': as_dict(db.get(Lead, src.lead_id)) if src else None, 'idempotent': True}
    it = Interaction(**body.model_dump(exclude={'auto_classify'}))
    db.add(it)
    db.flush()
    lead = classify_interaction(db, it) if body.auto_classify else None
    db.commit()
    return {'interaction_id': it.id, 'classify_status': it.classify_status,
            'classify_error': it.classify_error, 'lead': as_dict(lead) if lead else None}


@api.post('/interactions/{iid}/classify', tags=['互动线索'])
def classify(iid: int, db: Session = Depends(get_db), _=Depends(operate)):
    from .classifier import classify_interaction
    it = row(db, Interaction, iid)
    lead = classify_interaction(db, it)
    db.commit()
    return {'interaction': as_dict(it), 'lead': as_dict(lead) if lead else None}


@api.get('/leads', tags=['互动线索'])
def leads(status: str | None = None, intent: str | None = None, assignee: str | None = None,
          limit: int = Query(200, ge=1, le=500), db: Session = Depends(get_db), user=Depends(current_user)):
    q = lead_scope(select(Lead).order_by(Lead.id.desc()), user)
    if status:
        q = q.where(Lead.status == status)
    if intent:
        q = q.where(Lead.intent == intent)
    if assignee:
        q = q.where(Lead.assignee == assignee)
    return [as_dict(x) for x in db.scalars(q.limit(limit)).all()]


@api.get('/leads/{lid}', tags=['互动线索'])
def lead(lid: int, db: Session = Depends(get_db), user=Depends(current_user)):
    obj = visible_lead(db, lid, user)
    return {**as_dict(obj), 'sources': [as_dict(s) for s in db.scalars(select(LeadSource).where(LeadSource.lead_id == lid)).all()],
            'followups': [as_dict(f) for f in db.scalars(select(LeadFollowup).where(LeadFollowup.lead_id == lid)).all()]}


@api.put('/leads/{lid}', tags=['互动线索'])
def update_lead(lid: int, body: LeadUpdate, db: Session = Depends(get_db), user=Depends(current_user)):
    from .notify import enqueue_lead
    obj = visible_lead(db, lid, user, body.expected_version)
    if user.role == 'sales' and body.assignee is not None:
        raise HTTPException(403, '销售不能重新指派线索')
    if body.assignee:
        target = db.scalar(select(User).where(User.username == body.assignee, User.role == 'sales', User.enabled.is_(True)))
        if not target:
            raise HTTPException(422, '负责人必须是启用的销售账号名')
    old_status, old_assignee = obj.status, obj.assignee
    for k, value in body.model_dump(exclude={'expected_version'}, exclude_none=True).items():
        setattr(obj, k, value)
    db.add(LeadFollowup(lead_id=lid, actor_id=user.id, old_status=old_status,
                       new_status=obj.status, note=body.follow_notes or ('指派给：' + obj.assignee if body.assignee is not None else '')))
    db.flush()
    if old_assignee != obj.assignee or old_status != obj.status:
        enqueue_lead(db, obj, f'update:{obj.version}')
    db.commit()
    return as_dict(obj)


@api.post('/leads/{lid}/push', tags=['推送'])
def push_lead(lid: int, db: Session = Depends(get_db), user=Depends(operate)):
    from .notify import deliver, enqueue_lead
    obj = visible_lead(db, lid, user)
    events = enqueue_lead(db, obj, f'manual:{obj.version}')
    db.commit()
    for event in events:
        deliver(db, event)
        db.commit()
    return {'outbox': [as_dict(e) for e in events], 'pushed': all(e.status == 'sent' for e in events)}


@api.get('/outbox', tags=['推送'])
def outbox(status: str | None = None, lead_id: int | None = None, db: Session = Depends(get_db), _=Depends(operate)):
    q = select(Outbox).order_by(Outbox.id.desc())
    if status:
        q = q.where(Outbox.status == status)
    if lead_id:
        q = q.where(Outbox.lead_id == lead_id)
    return [as_dict(x) for x in db.scalars(q.limit(500)).all()]


@api.post('/outbox/process', tags=['推送'])
def process_outbox(db: Session = Depends(get_db), _=Depends(operate)):
    from .notify import process_due
    return {'processed': process_due(db)}


@api.post('/outbox/{oid}/retry', tags=['推送'])
def retry_outbox(oid: int, db: Session = Depends(get_db), _=Depends(operate)):
    from .notify import retry_event
    obj = row(db, Outbox, oid)
    retry_event(db, obj)
    db.commit()
    return as_dict(obj)


@api.get('/dashboard/funnel', tags=['看板'])
def funnel(db: Session = Depends(get_db), _=Depends(operate)):
    published = db.scalar(select(func.count()).select_from(ContentVariant).where(
        ContentVariant.status == 'published', ContentVariant.published_url != '', ContentVariant.published_at.is_not(None))) or 0
    views = db.scalar(select(func.coalesce(func.sum(Metric.views), 0))) or 0
    return {'published': published, 'views': views,
            'interactions': db.scalar(select(func.count(Interaction.id))) or 0,
            'leads': db.scalar(select(func.count(Lead.id))) or 0,
            'high_intent': db.scalar(select(func.count(Lead.id)).where(Lead.intent == 'high')) or 0}


@api.get('/dashboard/topics', tags=['看板'])
def dashboard_topics(db: Session = Depends(get_db), _=Depends(operate)):
    result = []
    for t in db.scalars(select(Topic).order_by(Topic.id)).all():
        published = db.scalar(select(func.count(ContentVariant.id)).join(Content).where(
            Content.topic_id == t.id, ContentVariant.status == 'published', ContentVariant.published_url != '')) or 0
        stats = db.execute(select(func.coalesce(func.sum(Metric.views), 0), func.coalesce(func.sum(Metric.likes), 0))
            .join(ContentVariant, Metric.variant_id == ContentVariant.id).join(Content, ContentVariant.content_id == Content.id)
            .where(Content.topic_id == t.id)).one()
        result.append({'topic_id': t.id, 'title': t.title, 'biz_line': t.biz_line, 'score': t.score,
                       'published': published, 'views': stats[0], 'likes': stats[1]})
    return result


@api.get('/dashboard/trend', tags=['看板'])
def dashboard_trend(start: date | None = None, end: date | None = None, db: Session = Depends(get_db), _=Depends(operate)):
    end = end or date.today()
    start = start or end - timedelta(days=6)
    if start > end or (end - start).days > 365:
        raise HTTPException(422, '日期区间须在0-365天内')
    # 分组聚合避免指标×互动join导致倍增，缺省日期补零。
    published = dict(db.execute(select(func.date(ContentVariant.published_at), func.count(ContentVariant.id))
        .where(ContentVariant.status == 'published', ContentVariant.published_url != '')
        .group_by(func.date(ContentVariant.published_at))).all())
    views = dict(db.execute(select(Metric.stat_date, func.sum(Metric.views)).group_by(Metric.stat_date)).all())
    interactions = dict(db.execute(select(func.date(Interaction.created_at), func.count(Interaction.id))
        .group_by(func.date(Interaction.created_at))).all())
    leads = dict(db.execute(select(func.date(Lead.created_at), func.count(Lead.id)).group_by(func.date(Lead.created_at))).all())
    normalized = lambda d: {str(k): v for k, v in d.items()}
    published, views, interactions, leads = map(normalized, (published, views, interactions, leads))
    return [{'date': str(start + timedelta(days=i)), 'published': published.get(str(start + timedelta(days=i)), 0),
             'views': views.get(str(start + timedelta(days=i)), 0), 'interactions': interactions.get(str(start + timedelta(days=i)), 0),
             'leads': leads.get(str(start + timedelta(days=i)), 0)} for i in range((end - start).days + 1)]


@api.get('/reports/weekly', tags=['复盘'])
def weekly(db: Session = Depends(get_db), _=Depends(operate)):
    return [as_dict(x) for x in db.scalars(select(WeeklyReport).order_by(WeeklyReport.week_start.desc()).limit(100)).all()]

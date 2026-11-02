from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .auth import current_user, hash_password, make_token, require_role, verify_password
from .classifier import classify_interaction
from .db import get_db
from .generator import generate_daily
from .models import (
    ComplianceRule, Content, ContentVariant, Interaction, Lead, Material,
    Metric, Topic, User, WeeklyReport,
)
from .notify import push_lead
from .schemas import (
    InteractionIn, LeadUpdate, LoginIn, MaterialIn, MetricIn, PublishIn,
    ReviewIn, RuleIn, TopicIn, UserIn, VariantUpdate,
)
from .storage import put

api = APIRouter()

# ---------- 认证 ----------

@api.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.username == body.username))
    if not u or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "账号或密码错误")
    return {"token": make_token(u), "user": {"id": u.id, "name": u.name, "role": u.role}}


@api.get("/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "name": user.name, "role": user.role}


# ---------- 用户管理(admin) ----------

@api.get("/users")
def list_users(db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    return [{"id": u.id, "username": u.username, "name": u.name, "role": u.role}
            for u in db.scalars(select(User)).all()]


@api.post("/users")
def create_user(body: UserIn, db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(400, "用户名已存在")
    u = User(username=body.username, password_hash=hash_password(body.password),
             name=body.name, role=body.role)
    db.add(u); db.commit(); db.refresh(u)
    return {"id": u.id}


# ---------- 素材库 ----------

def _mat_dict(m: Material) -> dict:
    return {k: getattr(m, k) for k in
            ("id", "category", "biz_line", "title", "content", "file_url",
             "publicity", "tags", "enabled")}


@api.get("/materials")
def list_materials(category: str | None = None, biz_line: str | None = None,
                   db: Session = Depends(get_db), _=Depends(current_user)):
    q = select(Material).order_by(Material.category, Material.id)
    if category:
        q = q.where(Material.category == category)
    if biz_line:
        q = q.where(Material.biz_line.in_([biz_line, "both"]))
    return [_mat_dict(m) for m in db.scalars(q).all()]


@api.post("/materials")
def create_material(body: MaterialIn, db: Session = Depends(get_db),
                    _=Depends(require_role("admin", "operator"))):
    m = Material(**body.model_dump())
    db.add(m); db.commit(); db.refresh(m)
    return _mat_dict(m)


@api.put("/materials/{mid}")
def update_material(mid: int, body: MaterialIn, db: Session = Depends(get_db),
                    _=Depends(require_role("admin", "operator"))):
    m = db.get(Material, mid) or (_ for _ in ()).throw(HTTPException(404))
    for k, v in body.model_dump().items():
        setattr(m, k, v)
    db.commit()
    return _mat_dict(m)


@api.delete("/materials/{mid}")
def del_material(mid: int, db: Session = Depends(get_db),
                 _=Depends(require_role("admin"))):
    m = db.get(Material, mid)
    if m:
        db.delete(m); db.commit()
    return {"ok": True}


@api.post("/materials/{mid}/file")
def upload_material_file(mid: int, f: UploadFile = File(...),
                         db: Session = Depends(get_db),
                         _=Depends(require_role("admin", "operator"))):
    m = db.get(Material, mid) or (_ for _ in ()).throw(HTTPException(404))
    url = put(f.file.read(), f.filename or "file", f.content_type or "")
    m.file_url = url
    db.commit()
    return {"file_url": url}


# ---------- 选题池 ----------

@api.get("/topics")
def list_topics(biz_line: str | None = None, status: str = "active",
                db: Session = Depends(get_db), _=Depends(current_user)):
    q = select(Topic).where(Topic.status == status).order_by(Topic.score.desc())
    if biz_line:
        q = q.where(Topic.biz_line == biz_line)
    return [{"id": t.id, "biz_line": t.biz_line, "theme": t.theme, "title": t.title,
             "angle": t.angle, "score": t.score, "status": t.status}
            for t in db.scalars(q).all()]


@api.post("/topics")
def create_topic(body: TopicIn, db: Session = Depends(get_db),
                 _=Depends(require_role("admin", "operator"))):
    t = Topic(**body.model_dump())
    db.add(t); db.commit(); db.refresh(t)
    return {"id": t.id}


@api.put("/topics/{tid}/status")
def topic_status(tid: int, status: str, db: Session = Depends(get_db),
                 _=Depends(require_role("admin", "operator"))):
    t = db.get(Topic, tid) or (_ for _ in ()).throw(HTTPException(404))
    t.status = status; db.commit()
    return {"ok": True}


# ---------- 合规红线 ----------

@api.get("/rules")
def list_rules(db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    return [{"id": r.id, "rule_type": r.rule_type, "pattern": r.pattern,
             "note": r.note, "enabled": r.enabled}
            for r in db.scalars(select(ComplianceRule)).all()]


@api.post("/rules")
def create_rule(body: RuleIn, db: Session = Depends(get_db),
                _=Depends(require_role("admin"))):
    r = ComplianceRule(**body.model_dump())
    db.add(r); db.commit(); db.refresh(r)
    return {"id": r.id}


@api.delete("/rules/{rid}")
def del_rule(rid: int, db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    r = db.get(ComplianceRule, rid)
    if r:
        db.delete(r); db.commit()
    return {"ok": True}


# ---------- 内容生成与审核 ----------

def _variant_dict(v: ContentVariant) -> dict:
    return {"id": v.id, "platform": v.platform, "body": v.body,
            "cover_text": v.cover_text, "hashtags": v.hashtags,
            "image_prompt": v.image_prompt, "best_time": v.best_time,
            "compliance_ok": v.compliance_ok, "compliance_hits": v.compliance_hits,
            "quality_score": v.quality_score, "quality_note": v.quality_note,
            "confirm_status": v.confirm_status, "publish_status": v.publish_status,
            "publish_error": v.publish_error,
            "published_url": v.published_url,
            "published_at": v.published_at.isoformat() if v.published_at else None}


def _content_dict(c: Content, with_variants=True) -> dict:
    d = {"id": c.id, "title": c.title, "biz_line": c.biz_line, "status": c.status,
         "source": c.source, "review_note": c.review_note,
         "scheduled_date": c.scheduled_date.isoformat() if c.scheduled_date else None,
         "topic": c.topic.title if c.topic else None}
    if with_variants:
        d["variants"] = [_variant_dict(v) for v in c.variants]
    return d


_gen_state = {"running": False, "last": None}


@api.post("/generate/daily")
def gen_daily(scheduled: date | None = None, _=Depends(require_role("admin", "operator"))):
    """异步生成：立即返回，后台跑完写库。避免 LLM 串行调用超时。"""
    import threading
    if _gen_state["running"]:
        return {"ok": False, "msg": "正在生成中，请稍后", "state": _gen_state}
    def run():
        _gen_state["running"] = True
        from .db import SessionLocal
        db = SessionLocal()
        try:
            cs = generate_daily(db, scheduled)
            _gen_state["last"] = {"count": len(cs), "titles": [c.title for c in cs]}
        except Exception as e:
            _gen_state["last"] = {"error": str(e)}
        finally:
            _gen_state["running"] = False
            db.close()
    threading.Thread(target=run, daemon=True).start()
    return {"ok": True, "msg": "已触发后台生成，约2-4分钟后到「内容管理」查看"}


@api.get("/generate/status")
def gen_status(_=Depends(current_user)):
    return _gen_state


@api.get("/contents")
def list_contents(status: str | None = None, scheduled: date | None = None,
                  db: Session = Depends(get_db), _=Depends(current_user)):
    q = (select(Content).options(selectinload(Content.variants),
                                 selectinload(Content.topic))
         .order_by(Content.scheduled_date.desc(), Content.id.desc()))
    if status:
        q = q.where(Content.status == status)
    if scheduled:
        q = q.where(Content.scheduled_date == scheduled)
    return [_content_dict(c) for c in db.scalars(q.limit(100)).all()]


@api.put("/variants/{vid}")
def update_variant(vid: int, body: VariantUpdate, db: Session = Depends(get_db),
                   _=Depends(require_role("admin", "operator"))):
    v = db.get(ContentVariant, vid) or (_ for _ in ()).throw(HTTPException(404))
    for k, val in body.model_dump(exclude_none=True).items():
        setattr(v, k, val)
    from .generator import check_compliance
    ok, hits = check_compliance(db, (v.body or "") + (v.cover_text or ""))
    v.compliance_ok, v.compliance_hits = ok, ",".join(hits)
    db.commit()
    return _variant_dict(v)


@api.post("/contents/{cid}/review")
def review(cid: int, body: ReviewIn, db: Session = Depends(get_db),
           _=Depends(require_role("admin", "operator"))):
    c = db.get(Content, cid) or (_ for _ in ()).throw(HTTPException(404))
    if body.action == "approve":
        c.status = "approved"
    elif body.action == "reject":
        c.status = "rejected"
        c.review_note = body.note
    else:
        raise HTTPException(400, "action 须为 approve/reject")
    db.commit()
    return {"id": c.id, "status": c.status}


@api.post("/variants/{vid}/publish")
def publish(vid: int, body: PublishIn, db: Session = Depends(get_db),
            _=Depends(current_user)):
    v = db.get(ContentVariant, vid) or (_ for _ in ()).throw(HTTPException(404))
    v.published_url = body.published_url
    v.published_at = datetime.now()
    v.publish_status = "published"
    if all(x.published_url or x.platform == "gzh" for x in v.content.variants):
        v.content.status = "published"
    db.commit()
    return _variant_dict(v)


# ---------- 待确认 + 一键确认发布 ----------

@api.get("/confirm/pending")
def confirm_pending(db: Session = Depends(get_db), _=Depends(current_user)):
    """待确认列表：AI质检达标的变体，等你点确认。"""
    rows = db.scalars(
        select(ContentVariant).join(Content)
        .where(ContentVariant.confirm_status == "pending")
        .order_by(ContentVariant.quality_score.desc())
    ).all()
    return [{**_variant_dict(v), "content_title": v.content.title,
             "biz_line": v.content.biz_line} for v in rows]


@api.post("/variants/{vid}/confirm")
def confirm_and_publish(vid: int, db: Session = Depends(get_db),
                        _=Depends(current_user)):
    """你点确认 → 系统自动发布到官方API。"""
    v = db.get(ContentVariant, vid) or (_ for _ in ()).throw(HTTPException(404))
    if v.confirm_status != "pending":
        raise HTTPException(400, "该内容不在待确认状态")
    v.confirm_status = "confirmed"
    db.commit()
    from .publisher import publish_variant
    r = publish_variant(db, v)
    if r["ok"] and all(x.publish_status == "published" or x.platform not in ("gzh", "douyin")
                       for x in v.content.variants):
        v.content.status = "published"
        db.commit()
    return {**_variant_dict(v), "publish_result": r}


@api.post("/variants/{vid}/confirm-reject")
def confirm_reject(vid: int, db: Session = Depends(get_db),
                   _=Depends(current_user)):
    v = db.get(ContentVariant, vid) or (_ for _ in ()).throw(HTTPException(404))
    v.confirm_status = "rejected"
    db.commit()
    return _variant_dict(v)


# ---------- 浏览器代理（右侧平台窗口：扫码登录 + 网页自动发布） ----------

@api.get("/browser/{platform}/open")
async def browser_open(platform: str, _=Depends(current_user)):
    """打开某平台后台/登录页，返回截图给用户扫码。"""
    if platform not in ("gzh", "douyin", "shipinhao", "xhs"):
        raise HTTPException(400, "不支持的平台")
    from .browser_agent import open_platform
    return await open_platform(platform)


@api.get("/browser/{platform}/screenshot")
async def browser_shot(platform: str, _=Depends(current_user)):
    """轮询当前页面画面+登录态。"""
    if platform not in ("gzh", "douyin", "shipinhao", "xhs"):
        raise HTTPException(400, "不支持的平台")
    from .browser_agent import screenshot
    return await screenshot(platform)


@api.post("/browser/{platform}/publish")
async def browser_publish(platform: str, body: dict, _=Depends(current_user)):
    """网页自动发布/填稿。body={title, body_html, video_path?, biz_line?}。"""
    title = body.get("title", "")
    body_html = body.get("body_html", "")
    video_path = body.get("video_path", "")
    biz_line = body.get("biz_line", "channel")
    if platform == "gzh":
        from .browser_agent import gzh_publish_draft
        return await gzh_publish_draft(title, body_html)
    if platform == "douyin":
        from .browser_agent import douyin_publish_draft
        return await douyin_publish_draft(title, body_html, video_path, biz_line)
    if platform == "xhs":
        from .browser_agent import xhs_publish_draft
        return await xhs_publish_draft(title, body_html, video_path, biz_line)
    if platform == "shipinhao":
        from .browser_agent import shipinhao_publish_draft
        return await shipinhao_publish_draft(title, body_html, video_path, biz_line)
    raise HTTPException(400, "该平台暂不支持网页自动发布")


# ---------- 平台凭据配置 ----------

PLATFORM_HOME = {
    "gzh": "https://mp.weixin.qq.com",
    "douyin": "https://creator.douyin.com",
    "shipinhao": "https://channels.weixin.qq.com",
    "xhs": "https://creator.xiaohongshu.com",
    "moments": "",
}


@api.get("/accounts/status")
def accounts_status(db: Session = Depends(get_db), _=Depends(current_user)):
    """所有用户可见：各平台是否已接好API（不泄露密钥）。"""
    from .models import PlatformAccount
    rows = {a.platform: a for a in db.scalars(select(PlatformAccount)).all()}
    out = []
    for pf in ("gzh", "douyin", "shipinhao", "xhs", "moments"):
        a = rows.get(pf)
        auto = bool(a and a.appid and a.enabled)
        out.append({"platform": pf, "auto": auto,
                    "home": PLATFORM_HOME.get(pf, ""),
                    "mode": "auto" if auto else "copy"})
    return out




@api.get("/accounts")
def list_accounts(db: Session = Depends(get_db), _=Depends(require_role("admin"))):
    from .models import PlatformAccount
    return [{"id": a.id, "platform": a.platform, "appid": a.appid,
             "configured": bool(a.appid), "enabled": a.enabled,
             "extra": a.extra}
            for a in db.scalars(select(PlatformAccount)).all()]


@api.post("/accounts")
def set_account(body: dict, db: Session = Depends(get_db),
                _=Depends(require_role("admin"))):
    """{platform, appid, appsecret, extra:{open_id,...}}"""
    from .models import PlatformAccount
    acc = db.scalar(select(PlatformAccount).where(
        PlatformAccount.platform == body["platform"]))
    if not acc:
        acc = PlatformAccount(platform=body["platform"])
        db.add(acc)
    acc.appid = body.get("appid", acc.appid)
    acc.appsecret = body.get("appsecret", acc.appsecret)
    acc.extra = body.get("extra", acc.extra)
    acc.enabled = body.get("enabled", True)
    db.commit()
    return {"id": acc.id, "platform": acc.platform}


# ---------- 今日待办 ----------

@api.get("/todo/today")
def todo_today(db: Session = Depends(get_db), _=Depends(current_user)):
    today = date.today()
    rows = db.scalars(
        select(Content)
        .options(selectinload(Content.variants))
        .where(Content.scheduled_date <= today,
               Content.status.in_(["draft", "approved"]))
        .order_by(Content.scheduled_date)
    ).all()
    items = []
    for c in rows:
        for v in c.variants:
            if not v.published_url:
                items.append({**_variant_dict(v), "content_id": c.id,
                              "content_title": c.title, "biz_line": c.biz_line,
                              "status": c.status})
    return {"date": today.isoformat(), "pending": items}


# ---------- 数据回流 ----------

@api.post("/metrics")
def add_metric(body: MetricIn, db: Session = Depends(get_db), _=Depends(current_user)):
    m = db.scalar(select(Metric).where(Metric.variant_id == body.variant_id,
                                       Metric.stat_date == body.stat_date))
    if m is None:
        m = Metric(**body.model_dump())
        db.add(m)
    else:
        for k, v in body.model_dump().items():
            if k not in ("variant_id", "stat_date"):
                setattr(m, k, v)
    db.commit()
    return {"ok": True}


@api.post("/upload/screenshot")
async def upload_screenshot(kind: str = Form(...), variant_id: int | None = Form(None),
                            f: UploadFile = File(...),
                            db: Session = Depends(get_db), _=Depends(current_user)):
    """kind=metrics|comments。OCR 解析待接入，先存图返回URL供人工录入。"""
    data = await f.read()
    url = put(data, f.filename or "shot.png", f.content_type or "image/png")
    return {"url": url, "kind": kind, "variant_id": variant_id,
            "ocr": "pending", "note": "OCR 待接入，请先手工录入数据"}


# ---------- 评论与线索 ----------

@api.post("/interactions")
def add_interaction(body: InteractionIn, db: Session = Depends(get_db),
                    _=Depends(current_user)):
    it = Interaction(platform=body.platform, kind=body.kind,
                     author_name=body.author_name, author_id=body.author_id,
                     body=body.body, variant_id=body.variant_id)
    db.add(it); db.commit(); db.refresh(it)
    result = {"interaction_id": it.id}
    if body.auto_classify:
        lead = classify_interaction(db, it)
        result["lead"] = _lead_dict(lead)
    return result


@api.get("/leads")
def list_leads(status: str | None = None, intent: str | None = None,
               db: Session = Depends(get_db), _=Depends(current_user)):
    q = select(Lead).order_by(Lead.id.desc())
    if status:
        q = q.where(Lead.status == status)
    if intent:
        q = q.where(Lead.intent == intent)
    return [_lead_dict(x) for x in db.scalars(q.limit(200)).all()]


def _lead_dict(x: Lead) -> dict:
    return {"id": x.id, "platform": x.platform, "visitor_name": x.visitor_name,
            "intent": x.intent, "identity": x.identity,
            "need_summary": x.need_summary, "contact_info": x.contact_info,
            "brand_need": x.brand_need, "reply_suggestion": x.reply_suggestion,
            "assignee": x.assignee, "status": x.status, "follow_notes": x.follow_notes,
            "created_at": x.created_at.isoformat()}


@api.put("/leads/{lid}")
def update_lead(lid: int, body: LeadUpdate, db: Session = Depends(get_db),
                _=Depends(current_user)):
    x = db.get(Lead, lid) or (_ for _ in ()).throw(HTTPException(404))
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(x, k, v)
    db.commit()
    return _lead_dict(x)


@api.post("/leads/{lid}/push")
def repush_lead(lid: int, db: Session = Depends(get_db), _=Depends(current_user)):
    x = db.get(Lead, lid) or (_ for _ in ()).throw(HTTPException(404))
    return {"pushed": push_lead(x)}


# ---------- 看板与复盘 ----------

@api.get("/llm/status")
def llm_status(_=Depends(current_user)):
    from .llm import status
    return status()


@api.get("/dashboard/funnel")
def funnel(db: Session = Depends(get_db), _=Depends(current_user)):
    published = db.scalar(select(func.count(ContentVariant.id))
                          .where(ContentVariant.published_url != "")) or 0
    views = db.scalar(select(func.coalesce(func.sum(Metric.views), 0))) or 0
    interactions = db.scalar(select(func.count(Interaction.id))) or 0
    leads = db.scalar(select(func.count(Lead.id))) or 0
    high = db.scalar(select(func.count(Lead.id)).where(Lead.intent == "high")) or 0
    return {"published": published, "views": views,
            "interactions": interactions, "leads": leads, "high_intent": high}


@api.get("/reports/weekly")
def weekly_reports(db: Session = Depends(get_db), _=Depends(current_user)):
    return [{"id": r.id, "week_start": r.week_start.isoformat(),
             "report_md": r.report_md}
            for r in db.scalars(select(WeeklyReport)
                                .order_by(WeeklyReport.week_start.desc())).all()]

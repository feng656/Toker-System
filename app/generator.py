"""每日内容包生成 + 合规检查。"""
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .llm import chat_json
from .models import ComplianceRule, Content, ContentVariant, Material, Topic

PLATFORMS = ["douyin", "shipinhao", "gzh", "moments"]

PLATFORM_STYLE = {
    "douyin": "60秒口播脚本，口语化，开头3秒抛出痛点钩子，结尾引导私信咨询",
    "shipinhao": "同口播但更沉稳，偏行业分享口吻",
    "gzh": "800-1500字深度图文，有结构小标题，专业可信",
    "moments": "3-5行朋友圈短文案，口语化配1个钩子，适合销售转发",
}

SYS = """你是云南自由光科技有限公司的新媒体内容策划。公司背景：弱电智能化/音视频行业「产品+服务」集成商，
京东方LED云南省总代、大华金牌代理、TCL一级代理等；两条业务线：
- project(甲方线)：面向政企甲方，卖点=总代正品+大项目案例+全省交付服务
- channel(渠道线)：面向工程商，卖点=不面对甲方不抢客户+2000万现货+资质赋能投标+带证技术劳务输出
硬性要求：正文与话术绝不出现具体底价/成本价；涉密案例不点名客户；遵守广告法。
输出JSON：{"body":...,"cover_text":...,"hashtags":...,"image_prompt":...,"best_time":...}，键名固定。"""


def pick_topics(db: Session, n_per_line: int = 1) -> list[Topic]:  # 先跑通，1甲1渠道
    out = []
    for line in ("project", "channel"):
        rows = db.scalars(
            select(Topic)
            .where(Topic.biz_line == line, Topic.status == "active")
            .order_by(Topic.score.desc(), Topic.last_used_at.asc().nulls_first())
            .limit(n_per_line)
        ).all()
        out.extend(rows)
    return out


def _materials_brief(db: Session, biz_line: str) -> str:
    rows = db.scalars(
        select(Material).where(
            Material.enabled.is_(True),
            Material.publicity != "internal",
            Material.biz_line.in_([biz_line, "both"]),
        ).limit(40)
    ).all()
    # 截断单条素材，避免prompt过长
    return "\n".join(f"[{m.category}] {m.title}: {m.content[:200]}" for m in rows)


def check_compliance(db: Session, text: str) -> tuple[bool, list[str]]:
    rules = db.scalars(select(ComplianceRule).where(ComplianceRule.enabled.is_(True))).all()
    hits = [r.pattern for r in rules if r.rule_type in ("forbidden", "ad_law") and r.pattern in text]
    return (not hits, hits)


def _gen_master(db: Session, t: Topic) -> dict:
    """先生成一份综合文案，再按平台改写。减少LLM调用次数。"""
    brief = _materials_brief(db, t.biz_line)
    user = f"选题：{t.title}\n切入角度：{t.angle}\n业务线：{t.biz_line}\n\n可用素材：\n{brief}\n\n先写一份300字左右的通用文案（核心卖点+行动引导），然后给出douyin/shipinhao/gzh/moments四个平台的改写版本，输出JSON：{{\"master\":\"通用文案\",\"douyin\":{{\"body\":...,\"cover_text\":...,\"hashtags\":...}},\"shipinhao\":{{...}},\"gzh\":{{...}},\"moments\":{{...}}}}"
    return chat_json(SYS, user)


def generate_daily(db: Session, target: date | None = None) -> list[Content]:
    target = target or date.today() + timedelta(days=1)
    topics = pick_topics(db)
    created = []
    for t in topics:
        data = _gen_master(db, t)
        c = Content(topic_id=t.id, biz_line=t.biz_line, title=t.title,
                    scheduled_date=target, status="draft")
        db.add(c)
        db.flush()
        for pf in PLATFORMS:
            vd = data.get(pf) or {}
            body = vd.get("body", "") or data.get("master", "")
            ok, hits = check_compliance(db, body + vd.get("cover_text", ""))
            db.add(ContentVariant(
                content_id=c.id, platform=pf, body=body,
                cover_text=vd.get("cover_text", "")[:200],
                hashtags=vd.get("hashtags", "")[:500],
                image_prompt=vd.get("image_prompt", "") or "配图建议：仓库/展厅/案例实拍",
                best_time=str(vd.get("best_time", "18:00-20:00"))[:100],
                compliance_ok=ok, compliance_hits=",".join(hits),
            ))
        t.last_used_at = datetime.now()
        created.append(c)
        db.commit()
        # 生成后逐变体质检打分
        from .quality import score_variant
        for v in c.variants:
            score_variant(db, v, t.title)
    # 有达标内容 → 企微提醒去确认
    try:
        pending = [v for c in created for v in c.variants if v.confirm_status == "pending"]
        if pending:
            from .notify import remind_confirm
            remind_confirm(len(pending), pending[0].content.title)
    except Exception:
        pass
    return created

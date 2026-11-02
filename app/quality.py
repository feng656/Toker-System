"""AI 质量检查：生成后自动打分，达标进待确认，不达标退回。"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .llm import chat_json
from .models import ComplianceRule, ContentVariant

QUALITY_SYS = """你是B2B弱电行业内容质检员。给一条待发布文案打分(0-100)，输出JSON：
{"score":0-100, "note":"一句话评语", "issues":["问题1","问题2"]}
评分维度：与选题相关性(30)、有无具体价值/信息增量(25)、平台风格适配(15)、口语化程度(15)、有无明显违规/夸大(15)。
<60=不合格。"""


def score_variant(db: Session, v: ContentVariant, topic_title: str) -> ContentVariant:
    # 1. 合规硬检（词库）
    rules = db.scalars(select(ComplianceRule).where(ComplianceRule.enabled.is_(True))).all()
    hits = [r.pattern for r in rules
            if r.rule_type in ("forbidden", "ad_law") and r.pattern in (v.body + v.cover_text)]
    v.compliance_hits = ",".join(hits)
    v.compliance_ok = not hits

    # 2. AI 质检打分
    data = chat_json(QUALITY_SYS,
                     f"平台:{v.platform}\n选题:{topic_title}\n文案:\n{v.body}")
    v.quality_score = int(data.get("score", 0) or 0)
    v.quality_note = data.get("note", "")

    # 3. 状态流转：合规且分数>=70 → 待确认；否则退回草稿
    if v.compliance_ok and v.quality_score >= 70:
        v.confirm_status = "pending"
    else:
        v.confirm_status = "none"
        v.publish_status = "none"
    db.commit()
    return v

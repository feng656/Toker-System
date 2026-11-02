"""周复盘：聚合上周数据 → LLM 生成复盘报告 → 回写 topics.score。"""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .llm import chat
from .models import Content, ContentVariant, Lead, Metric, Topic, WeeklyReport

SYS = "你是B2B弱电行业新媒体运营分析师。根据给定的上周发布数据与线索数据，输出Markdown周报：" \
      "1)整体表现 2)各平台对比 3)表现最好/最差的内容及原因猜测 4)下周选题建议(5条)。务实简洁。"


def make_weekly_report(db: Session, week_start: date | None = None) -> WeeklyReport:
    ws = week_start or (date.today() - timedelta(days=7))
    we = ws + timedelta(days=7)

    rows = db.execute(
        select(Metric, ContentVariant, Content)
        .join(ContentVariant, Metric.variant_id == ContentVariant.id)
        .join(Content, ContentVariant.content_id == Content.id)
        .where(Metric.stat_date >= ws, Metric.stat_date < we)
    ).all()

    lines = []
    for m, v, c in rows:
        lines.append(f"{v.platform}|{c.title}|{c.biz_line}|播放{m.views}|赞{m.likes}|评{m.comments}|藏{m.collects}|私信{m.dm_inquiries}")
    leads = db.scalars(select(Lead).where(Lead.created_at >= ws,
                                          Lead.created_at < we)).all()
    lead_txt = "\n".join(f"{l.intent}|{l.identity}|{l.need_summary}" for l in leads)

    user = f"统计区间 {ws} ~ {we}\n\n内容数据:\n" + ("\n".join(lines) or "无") \
           + f"\n\n线索({len(leads)}条):\n" + (lead_txt or "无")
    report_md = chat(SYS, user)

    r = WeeklyReport(week_start=ws, report_md=report_md,
                     insights={"rows": len(rows), "leads": len(leads)})
    db.add(r)

    # 反哺选题分：相关选题按平均曝光调整
    for m, v, c in rows:
        if c.topic_id:
            t = db.get(Topic, c.topic_id)
            if t:
                t.score = round(t.score * 0.8 + (m.views + m.likes * 5) / 1000, 3)
    db.commit()
    db.refresh(r)
    return r

"""可重复周报；指标均按当天增量录入，选题反哺只执行一次。"""
import json
from datetime import date, timedelta
from sqlalchemy import select
from .llm import AIUnavailable, call_json
from .models import Content, ContentVariant, Lead, Metric, Topic, WeeklyReport
from .tasks import lock


def make_weekly_report(db, week_start=None):
    today = date.today()
    start = week_start or today - timedelta(days=today.weekday() + 7)
    end = start + timedelta(days=7)
    lock(db, f'weekly:{start}')
    old = db.scalar(select(WeeklyReport).where(WeeklyReport.week_start == start))
    if old:
        return old
    rows = db.execute(select(Metric, ContentVariant, Content)
        .join(ContentVariant, Metric.variant_id == ContentVariant.id)
        .join(Content, ContentVariant.content_id == Content.id)
        .where(Metric.stat_date >= start, Metric.stat_date < end)).all()
    leads = db.scalars(select(Lead).where(Lead.created_at >= start, Lead.created_at < end)).all()
    summary = {'start': str(start), 'end_exclusive': str(end), 'leads': len(leads),
               'metrics': [{'platform': v.platform, 'title': c.title, 'views': m.views, 'likes': m.likes}
                           for m, v, c in rows]}
    try:
        result = call_json(db, 'weekly', '依据统计生成运营复盘，JSON {"report_md":"Markdown"}，区分事实与推测。',
                           json.dumps(summary, ensure_ascii=False), context=summary)
        md = result.get('report_md', '')
        if not isinstance(md, str) or not md:
            raise AIUnavailable('周报正文为空')
    except AIUnavailable:
        db.commit()  # 保存失败调用日志，允许下次重试。
        return None
    report = WeeklyReport(week_start=start, report_md=md, insights=summary)
    db.add(report)
    topic_scores = {}
    for m, _, c in rows:
        if c.topic_id:
            topic_scores[c.topic_id] = topic_scores.get(c.topic_id, 0) + (m.views + m.likes * 5) / 1000
    for tid, score in topic_scores.items():
        topic = db.get(Topic, tid)
        if topic and not topic.deleted_at:
            topic.score = round(topic.score * 0.8 + score, 3)
    db.commit()
    return report

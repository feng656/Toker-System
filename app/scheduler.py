"""定时任务：每日08:00生成内容包；09:00/14:00待办催办；周一09:00周复盘。"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .db import SessionLocal

_sched = BackgroundScheduler(timezone="Asia/Shanghai")


def job_daily_generate():
    from .generator import generate_daily
    db = SessionLocal()
    try:
        generate_daily(db)
    finally:
        db.close()


def job_remind():
    from datetime import date
    from sqlalchemy import select
    from .models import Content, ContentVariant
    from .notify import remind_todo
    db = SessionLocal()
    try:
        n = db.query(ContentVariant).join(Content).filter(
            Content.scheduled_date <= date.today(),
            Content.status.in_(["draft", "approved"]),
            ContentVariant.published_url == "",
        ).count()
        if n:
            remind_todo(n)
    finally:
        db.close()


def job_weekly_report():
    from .report import make_weekly_report
    db = SessionLocal()
    try:
        make_weekly_report(db)
    finally:
        db.close()


def start_scheduler():
    if _sched.running:
        return
    _sched.add_job(job_daily_generate, CronTrigger(hour=8, minute=0), id="daily_gen")
    _sched.add_job(job_remind, CronTrigger(hour="9,14", minute=0), id="remind")
    _sched.add_job(job_weekly_report, CronTrigger(day_of_week="mon", hour=9), id="weekly")
    _sched.start()


def stop_scheduler():
    if _sched.running:
        _sched.shutdown(wait=False)

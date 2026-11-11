"""单独worker进程运行；PostgreSQL jobstore持久化，业务任务另有唯一幂等键。"""
from datetime import date
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from . import config
from .db import SessionLocal

_sched = None


def job_daily_generate():
    from .tasks import enqueue_daily, execute_daily
    with SessionLocal() as db:
        job = enqueue_daily(db)
        db.commit()
        execute_daily(db, job)


def job_remind():
    from sqlalchemy import select, func
    from .models import Content, ContentVariant
    from .notify import enqueue
    with SessionLocal() as db:
        n = db.scalar(select(func.count(ContentVariant.id)).join(Content).where(
            Content.scheduled_date <= date.today(), ContentVariant.is_current.is_(True),
            ContentVariant.confirm_status == 'confirmed', ContentVariant.status == 'pending')) or 0
        if n:
            from datetime import datetime
            enqueue(db, 'wecom', f'todo:{date.today()}:{datetime.now().hour}',
                    {'message': f'今日还有{n}条已审核内容待发布/回填，请到今日待办处理。'})
            db.commit()


def job_weekly_report():
    from .report import make_weekly_report
    with SessionLocal() as db:
        make_weekly_report(db)


def job_outbox():
    from .notify import process_due
    with SessionLocal() as db:
        process_due(db)


def job_pending():
    from sqlalchemy import select
    from .models import TaskExecution
    from .tasks import execute_daily, recover_stale
    with SessionLocal() as db:
        recover_stale(db)
        rows = db.scalars(select(TaskExecution).where(TaskExecution.status == 'pending').limit(10)).all()
        for task in rows:
            if task.kind == 'daily_generate':
                execute_daily(db, task)


def job_phase2():
    from .phase2_worker import tick
    tick()


def start_scheduler():
    global _sched
    if _sched and _sched.running:
        return
    _sched = BackgroundScheduler(timezone='Asia/Shanghai',
        jobstores={'default': SQLAlchemyJobStore(url=config.DATABASE_URL)},
        job_defaults={'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 3600})
    jobs = [('daily_gen', job_daily_generate, CronTrigger(hour=8, timezone='Asia/Shanghai')),
            ('remind', job_remind, CronTrigger(hour='9,14', timezone='Asia/Shanghai')),
            ('weekly', job_weekly_report, CronTrigger(day_of_week='mon', hour=9, timezone='Asia/Shanghai')),
            ('outbox', job_outbox, 'interval'), ('pending', job_pending, 'interval'),
            ('phase2', job_phase2, 'interval')]
    for key, fn, trigger in jobs:
        options = {'seconds': 30} if trigger == 'interval' else {}
        _sched.add_job(fn, trigger, id=key, replace_existing=True, **options)
    _sched.start()


def stop_scheduler():
    if _sched and _sched.running:
        _sched.shutdown(wait=True)

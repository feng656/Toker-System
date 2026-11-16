"""持久化任务执行；PostgreSQL事务级互斥+唯一键，跨进程幂等。"""
import hashlib
from datetime import date, timedelta
from sqlalchemy import select, text
from .db import utcnow
from .models import TaskExecution


def lock(db, key):
    if db.bind.dialect.name == 'postgresql':
        value = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], 'big', signed=True)
        db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': value})


def enqueue_daily(db, target=None):
    target = target or date.today() + timedelta(days=1)
    key = f'generate:{target}'
    lock(db, key)
    job = db.scalar(select(TaskExecution).where(TaskExecution.task_key == key))
    if not job:
        from .generator import pick_topics
        topics = pick_topics(db)
        if len(topics) < 2:
            raise ValueError('请先建立甲方线和渠道线选题')
        job = TaskExecution(task_key=key, kind='daily_generate',
                            payload={'scheduled': str(target), 'topic_ids': [t.id for t in topics]})
        db.add(job)
        db.flush()
    return job


def execute_daily(db, job):
    from .generator import generate_daily
    from .models import Topic
    lock(db, job.task_key)
    db.refresh(job)
    if job.status == 'succeeded':
        return job
    job.status, job.attempts, job.started_at = 'running', job.attempts + 1, utcnow()
    job.error = ''
    db.flush()
    # 业务包失败整体回滚；保存点内的每次AI调用在失败时重放审计，不保存提示词或凭据。
    from .models import AIJob
    db.info['ai_audit'] = []
    try:
        with db.begin_nested():
            topics = [db.get(Topic, tid) for tid in job.payload['topic_ids']]
            if any(t is None or t.deleted_at for t in topics):
                raise ValueError('任务选题不存在')
            contents = generate_daily(db, date.fromisoformat(job.payload['scheduled']), topics)
            result = {'count': len(contents), 'content_ids': [c.id for c in contents]}
        job.status, job.result = 'succeeded', result
    except Exception as exc:
        job.status = 'failed'
        job.error = type(exc).__name__ + ': ' + str(exc)[:800]
        for audit in db.info.get('ai_audit', []):
            db.add(AIJob(**audit))
        db.add(AIJob(kind='generation_validation', resource_id=job.id, status='failed',
                     input_hash=hashlib.sha256(job.task_key.encode()).hexdigest(), error=job.error))
    db.info.pop('ai_audit', None)
    job.finished_at = utcnow()
    db.commit()
    return job


def enqueue_video(db, prompt, *, variant_id=None, duration_sec=None, resolution=None,
                  aspect_ratio=None, model=None, seed=None, ref_image_path=None):
    """视频任务按内容哈希幂等：同一提示词+参数重复提交复用未失败的任务。

    参考图以文件路径入 payload，不把 base64 大块写进任务表。
    """
    payload = {'prompt': prompt, 'variant_id': variant_id, 'duration_sec': duration_sec,
               'resolution': resolution, 'aspect_ratio': aspect_ratio, 'model': model,
               'seed': seed, 'ref_image_path': ref_image_path}
    key = 'video:' + hashlib.sha256(
        (prompt + repr(sorted((k, v) for k, v in payload.items() if k != 'prompt'))).encode()).hexdigest()[:40]
    lock(db, key)
    job = db.scalar(select(TaskExecution).where(TaskExecution.task_key == key))
    if job and job.status in ('pending', 'running', 'succeeded'):
        return job
    if job:
        job.status, job.error, job.result = 'pending', '', {}
    else:
        job = TaskExecution(task_key=key, kind='video_generate', payload=payload)
        db.add(job)
    db.flush()
    return job


def execute_video(db, job):
    from . import video_provider
    lock(db, job.task_key)
    db.refresh(job)
    if job.status == 'succeeded':
        return job
    job.status, job.attempts, job.started_at = 'running', job.attempts + 1, utcnow()
    job.error = ''
    # 视频等待可达数分钟：先提交 running，轮询方能看到进度，也不长时间占着事务。
    db.commit()
    p = job.payload
    ref_image_base64 = None
    if p.get('ref_image_path'):
        import base64
        from pathlib import Path
        ref_image_base64 = base64.b64encode(Path(p['ref_image_path']).read_bytes()).decode()
    try:
        result = video_provider.generate(
            db, p['prompt'], resource_id=p.get('variant_id'),
            duration_sec=p.get('duration_sec'), resolution=p.get('resolution'),
            aspect_ratio=p.get('aspect_ratio'), model=p.get('model'), seed=p.get('seed'),
            ref_image_base64=ref_image_base64)
        job.status, job.result = 'succeeded', result
    except Exception as exc:
        job.status = 'failed'
        job.error = type(exc).__name__ + ': ' + str(exc)[:800]
    job.finished_at = utcnow()
    db.commit()
    return job


def recover_stale(db, minutes=15):
    rows = db.scalars(select(TaskExecution).where(TaskExecution.status == 'running',
               TaskExecution.started_at < utcnow() - timedelta(minutes=minutes))).all()
    for job in rows:
        job.status = 'failed'
        job.error = '执行进程中断或超时，可由管理接口重试'
    db.commit()
    return len(rows)

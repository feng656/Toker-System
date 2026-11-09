"""单副本调度入口。远端结果不确定时停止自动重试；人工核对后复用幂等键。
仅处理明确入队/人工批准的任务，不自行发现目标或批准内容。
"""
from datetime import timedelta
from fastapi import HTTPException
from sqlalchemy import select
from . import config
from .db import SessionLocal, utcnow
from .models import VideoJob, WorkspaceJob, CommentTask, CommentAction, DMMessage, LoginBucket, AuthChallenge


def recover(db):
    cutoff = utcnow() - timedelta(minutes=15)
    count = 0
    for model in (CommentAction, DMMessage):
        rows = db.scalars(select(model).where(model.status == 'sending', model.updated_at < cutoff).with_for_update(skip_locked=True)).all()
        for item in rows:
            item.status = 'uncertain'
            item.error = '发送进程中断；先核对远端状态，再人工按原幂等键重试，禁止自动补发'
            count += 1
    # 安全计数不永久留存IP/账号的散列历史；软删除会妨碍唯一键复用，此处只清理临时安全数据。
    from sqlalchemy import delete
    db.execute(delete(AuthChallenge).where(AuthChallenge.expires_at < utcnow()-timedelta(days=1)))
    db.execute(delete(LoginBucket).where(LoginBucket.window_started < utcnow()-timedelta(days=2)))
    db.commit()
    return count


def tick():
    if not config.PHASE2_WORKER_ENABLED:
        return
    from .media import run_video
    from .workspace import run_publish
    from .engagement import run_comments, send_dm
    with SessionLocal() as db:
        recover(db)
        videos = list(db.scalars(select(VideoJob.id).where(VideoJob.status.in_(['queued','running'])).limit(10)))
        publishes = list(db.scalars(select(WorkspaceJob.id).where(WorkspaceJob.status == 'queued').limit(10)))
        comments = list(db.scalars(select(CommentTask.id).where(CommentTask.status.in_(['approved','running'])).limit(10)))
        messages = list(db.scalars(select(DMMessage.id).where(DMMessage.status == 'approved').limit(10)))
    for model, ids in ((VideoJob,videos),(WorkspaceJob,publishes),(CommentTask,comments),(DMMessage,messages)):
        for key in ids:
            with SessionLocal() as db:
                obj = db.get(model,key)
                try:
                    if model is VideoJob:
                        run_video(db,obj)
                    elif model is WorkspaceJob:
                        run_publish(db,obj,None)  # 仅预览；绝不调用confirm。
                    elif config.AUTOMATION_ENABLED and model is CommentTask:
                        unresolved = db.scalar(select(CommentAction.id).where(CommentAction.task_id==key, CommentAction.status.in_(['sending','uncertain'])).limit(1))
                        if not unresolved:
                            run_comments(db,obj,obj.approved_by)
                    elif config.AUTOMATION_ENABLED and model is DMMessage:
                        send_dm(db,obj,obj.approved_by)
                except HTTPException:
                    db.rollback()  # 配额、会话或规则变化时不绕过；保留任务供页面查看。

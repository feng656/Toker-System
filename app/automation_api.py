from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from .api import operate, admin, row, as_dict
from .db import get_db, utcnow
from .models import (WorkspaceAccount, WorkspaceJob, ContentVariant, CommentTask, CommentAction,
                     ReplyTemplate, DMPolicy, DMMessage, AIProvider, AutomationEvent)
from .phase2_schemas import AccountIn, AccountLoginIn, PublishJobIn, CommentTaskIn, DiscoverIn, ReplyTemplateIn, DMPolicyIn, DMIn
from . import workspace, engagement, storage
from .tasks import lock

api = APIRouter()


@api.get('/workspace/accounts', tags=['工作空间'])
def accounts(db:Session=Depends(get_db),_=Depends(operate)):
    return [workspace.public_account(a) for a in db.scalars(select(WorkspaceAccount).order_by(WorkspaceAccount.id)).all()]


@api.post('/workspace/accounts', status_code=201, tags=['工作空间'])
def account(body:AccountIn,db:Session=Depends(get_db),_=Depends(admin)):
    from .platforms import resolve
    resolve(db,platform_id=body.platform_id,enabled=True)
    a=WorkspaceAccount(**body.model_dump());db.add(a);db.commit();return workspace.public_account(a)


@api.post('/workspace/accounts/{aid}/login', tags=['工作空间'])
def login(aid:int,body:AccountLoginIn,db:Session=Depends(get_db),actor=Depends(operate)):
    return workspace.login(db,row(db,WorkspaceAccount,aid),body,actor.id)


@api.post('/workspace/accounts/{aid}/refresh', tags=['工作空间'])
def refresh(aid:int,db:Session=Depends(get_db),actor=Depends(operate)):
    return workspace.refresh(db,row(db,WorkspaceAccount,aid),actor.id)


@api.post('/workspace/accounts/{aid}/logout', tags=['工作空间'])
def logout(aid:int,db:Session=Depends(get_db),actor=Depends(operate)):
    workspace.logout(db,row(db,WorkspaceAccount,aid),actor.id);return {'ok':True}


@api.get('/workspace/accounts/{aid}/session', tags=['工作空间'])
def session(aid:int,db:Session=Depends(get_db),_=Depends(operate)):
    a=row(db,WorkspaceAccount,aid);result=workspace.public_account(a)
    if result['qr_available']:result['qr_url']=storage.signed_url(a.qr_object_ref)
    return result


@api.post('/workspace/publish-jobs', status_code=201, tags=['沙盒发布'])
def publish_job(body:PublishJobIn,db:Session=Depends(get_db),actor=Depends(operate)):
    lock(db,'publish-key:'+body.request_key)
    job=db.scalar(select(WorkspaceJob).where(WorkspaceJob.request_key==body.request_key))
    if job:
        if job.account_id!=body.account_id or job.variant_id!=body.variant_id:raise HTTPException(409,'幂等键已被其他任务使用')
        return workspace.public_job(job)
    job=WorkspaceJob(**body.model_dump())
    workspace.eligible(db,job)
    db.add(job);db.flush();workspace.event(db,'publish',job.id,'queued',actor.id);db.commit()
    return workspace.public_job(job)


@api.get('/workspace/publish-jobs/{jid}', tags=['沙盒发布'])
def get_publish(jid:int,db:Session=Depends(get_db),_=Depends(operate)):
    return workspace.public_job(row(db,WorkspaceJob,jid))


@api.get('/workspace/publish-jobs/{jid}/steps/{index}/screenshot', tags=['沙盒发布'])
def step_screenshot(jid:int,index:int,db:Session=Depends(get_db),_=Depends(operate)):
    job=row(db,WorkspaceJob,jid)
    if not 0<=index<len(job.steps) or not job.steps[index].get('screenshot_ref'):raise HTTPException(404,'该步骤无截图')
    return {'url':storage.signed_url(job.steps[index]['screenshot_ref']),'expires_seconds':600}


@api.post('/workspace/publish-jobs/{jid}/run', tags=['沙盒发布'])
def run_publish(jid:int,db:Session=Depends(get_db),actor=Depends(operate)):
    return workspace.run_publish(db,row(db,WorkspaceJob,jid),actor.id)


@api.post('/workspace/publish-jobs/{jid}/confirm', tags=['沙盒发布'])
def confirm_publish(jid:int,db:Session=Depends(get_db),actor=Depends(operate)):
    return workspace.run_publish(db,row(db,WorkspaceJob,jid),actor.id,confirm=True)


@api.post('/workspace/publish-jobs/{jid}/retry', tags=['沙盒发布'])
def retry_publish(jid:int,db:Session=Depends(get_db),actor=Depends(operate)):
    return workspace.run_publish(db,row(db,WorkspaceJob,jid),actor.id,retry=True)


@api.post('/workspace/publish-jobs/{jid}/cancel', tags=['沙盒发布'])
def cancel_publish(jid:int,db:Session=Depends(get_db),actor=Depends(operate)):
    lock(db,f'workspace-job:{jid}');job=row(db,WorkspaceJob,jid)
    if job.status not in ('queued','failed','awaiting_confirmation'):raise HTTPException(409,'当前任务不可取消')
    job.status='cancelled';workspace.event(db,'publish',jid,'cancelled',actor.id);db.commit();return workspace.public_job(job)


@api.get('/workspace/overview', tags=['工作空间'])
def overview(db:Session=Depends(get_db),_=Depends(operate)):
    accounts=db.scalars(select(WorkspaceAccount)).all()
    jobs=db.scalars(select(WorkspaceJob).order_by(WorkspaceJob.id.desc()).limit(200)).all()
    today=utcnow().replace(hour=0,minute=0,second=0,microsecond=0)
    return {'accounts':[workspace.public_account(a) for a in accounts], 'jobs':[workspace.public_job(j) for j in jobs],
        'counts':{'published_today':db.scalar(select(func.count()).select_from(ContentVariant).where(ContentVariant.published_at>=today,ContentVariant.status=='published')),
        'queued':db.scalar(select(func.count()).select_from(WorkspaceJob).where(WorkspaceJob.status.in_(['queued','awaiting_confirmation','running']))),
        'failed':db.scalar(select(func.count()).select_from(WorkspaceJob).where(WorkspaceJob.status=='failed'))}}


def task_dict(db,task):
    return {**as_dict(task),'actions':[as_dict(a) for a in db.scalars(select(CommentAction).where(CommentAction.task_id==task.id).order_by(CommentAction.id)).all()]}


@api.post('/comment-tasks', status_code=201, tags=['授权评论'])
def comment_task(body:CommentTaskIn,db:Session=Depends(get_db),actor=Depends(operate)):
    row(db,WorkspaceAccount,body.account_id)
    if body.mode in ('manual','polish') and not body.draft:raise HTTPException(422,'自写或润色模式需要草稿')
    task=CommentTask(**body.model_dump());db.add(task);db.flush();workspace.event(db,'comment',task.id,'created',actor.id);db.commit()
    return task_dict(db,task)


@api.get('/comment-tasks', tags=['授权评论'])
def comment_tasks(db:Session=Depends(get_db),_=Depends(operate)):
    return [as_dict(t) for t in db.scalars(select(CommentTask).order_by(CommentTask.id.desc()).limit(200)).all()]


@api.get('/comment-tasks/{tid}', tags=['授权评论'])
def comment_detail(tid:int,db:Session=Depends(get_db),_=Depends(operate)):
    return task_dict(db,row(db,CommentTask,tid))


@api.post('/comment-tasks/{tid}/discover', tags=['授权评论'])
def discover(tid:int,body:DiscoverIn,db:Session=Depends(get_db),actor=Depends(operate)):
    return task_dict(db,engagement.discover(db,row(db,CommentTask,tid),body.search_confirmed,actor.id))


@api.post('/comment-tasks/{tid}/prepare', tags=['授权评论'])
def prepare(tid:int,db:Session=Depends(get_db),actor=Depends(operate)):
    return task_dict(db,engagement.prepare_comments(db,row(db,CommentTask,tid),actor.id))


@api.post('/comment-tasks/{tid}/approve', tags=['授权评论'])
def approve(tid:int,db:Session=Depends(get_db),actor=Depends(operate)):
    task=row(db,CommentTask,tid);engagement.approve_comments(db,task,actor.id);return task_dict(db,task)


@api.post('/comment-tasks/{tid}/run', tags=['授权评论'])
def run_comments(tid:int,db:Session=Depends(get_db),actor=Depends(operate)):
    return task_dict(db,engagement.run_comments(db,row(db,CommentTask,tid),actor.id))


@api.post('/comment-tasks/{tid}/stop', tags=['授权评论'])
@api.post('/comment-tasks/{tid}/cancel', tags=['授权评论'])
def stop_comments(tid:int,db:Session=Depends(get_db),actor=Depends(operate)):
    lock(db,f'comment:{tid}');task=row(db,CommentTask,tid)
    if task.status=='succeeded':raise HTTPException(409,'已完成任务不能取消')
    task.status='cancelled';workspace.event(db,'comment',tid,'cancelled',actor.id);db.commit()
    return {'status':task.status,'note':'停止后续发送；已在途的单条请求可能已发送，记录将保留'}


@api.post('/comment-tasks/{tid}/collect', tags=['授权评论'])
def collect(tid:int,db:Session=Depends(get_db),actor=Depends(operate)):
    return engagement.collect(db,row(db,CommentTask,tid),actor.id)


@api.get('/reply-templates', tags=['私信接管'])
def templates(db:Session=Depends(get_db),_=Depends(operate)):
    return [as_dict(t) for t in db.scalars(select(ReplyTemplate)).all()]


@api.post('/reply-templates', status_code=201, tags=['私信接管'])
def template_create(body:ReplyTemplateIn,db:Session=Depends(get_db),_=Depends(operate)):
    t=ReplyTemplate(**body.model_dump());db.add(t);db.commit();return as_dict(t)


@api.put('/reply-templates/{tid}', tags=['私信接管'])
def template_edit(tid:int,body:ReplyTemplateIn,db:Session=Depends(get_db),_=Depends(operate)):
    t=row(db,ReplyTemplate,tid)
    for k,v in body.model_dump().items():setattr(t,k,v)
    db.commit();return as_dict(t)


@api.get('/dm-policies', tags=['私信接管'])
def policies(db:Session=Depends(get_db),_=Depends(operate)):
    return [as_dict(p) for p in db.scalars(select(DMPolicy)).all()]


@api.post('/dm-policies', tags=['私信接管'])
def policy(body:DMPolicyIn,db:Session=Depends(get_db),actor=Depends(operate)):
    row(db,WorkspaceAccount,body.account_id)
    if body.mode=='fixed':
        if not body.template_id:raise HTTPException(422,'固定话术必须指定模板')
        row(db,ReplyTemplate,body.template_id)
    if body.mode=='ai' and body.provider_id:
        p=row(db,AIProvider,body.provider_id)
        if not p.enabled or p.capability!='text':raise HTTPException(422,'须选择启用的文本服务')
    if body.enabled and (not body.scope or body.window_start==body.window_end):raise HTTPException(422,'启用需要明确发送者范围和有效时间窗')
    lock(db,f'dm-policy:{body.account_id}')
    p=db.scalar(select(DMPolicy).where(DMPolicy.account_id==body.account_id))
    if not p:p=DMPolicy(account_id=body.account_id);db.add(p)
    for k,v in body.model_dump().items():setattr(p,k,v)
    db.flush();workspace.event(db,'dm_policy',p.id,'configured',actor.id);db.commit();return as_dict(p)


@api.post('/dm/messages', status_code=201, tags=['私信接管'])
def message(body:DMIn,db:Session=Depends(get_db),actor=Depends(operate)):
    import hashlib
    account=row(db,WorkspaceAccount,body.account_id)
    key='dm:'+hashlib.sha256(f'{body.account_id}:{body.source_key}'.encode()).hexdigest()
    lock(db,key)
    m=db.scalar(select(DMMessage).where(DMMessage.source_key==key))
    if m:
        if m.sender_id!=body.sender_id or m.body!=body.body:raise HTTPException(409,'入站事件ID已用于其他消息')
        return as_dict(m)
    m=DMMessage(**body.model_dump(exclude={'source_key'}),source_key=key);db.add(m);db.flush()
    engagement.inbound(db,account,body.source_key,body.sender_id,body.body,'dm')
    workspace.event(db,'dm',m.id,'received',actor.id);db.commit();return as_dict(m)


@api.get('/dm/messages', tags=['私信接管'])
def messages(db:Session=Depends(get_db),_=Depends(operate)):
    return [as_dict(m) for m in db.scalars(select(DMMessage).order_by(DMMessage.id.desc()).limit(200)).all()]


@api.post('/dm/messages/{mid}/prepare', tags=['私信接管'])
def prepare_dm(mid:int,db:Session=Depends(get_db),actor=Depends(operate)):
    return as_dict(engagement.prepare_dm(db,row(db,DMMessage,mid),actor.id))


@api.post('/dm/messages/{mid}/approve', tags=['私信接管'])
def approve_dm(mid:int,db:Session=Depends(get_db),actor=Depends(operate)):
    return as_dict(engagement.approve_dm(db,row(db,DMMessage,mid),actor.id))


@api.post('/dm/messages/{mid}/send', tags=['私信接管'])
def send_dm(mid:int,db:Session=Depends(get_db),actor=Depends(operate)):
    return as_dict(engagement.send_dm(db,row(db,DMMessage,mid),actor.id))


@api.get('/automation/events', tags=['自动化审计'])
def events(resource:str|None=None,resource_id:int|None=None,limit:int=Query(100,ge=1,le=500),db:Session=Depends(get_db),_=Depends(operate)):
    q=select(AutomationEvent).order_by(AutomationEvent.id.desc())
    if resource:q=q.where(AutomationEvent.resource==resource)
    if resource_id:q=q.where(AutomationEvent.resource_id==resource_id)
    return [as_dict(e) for e in db.scalars(q.limit(limit)).all()]

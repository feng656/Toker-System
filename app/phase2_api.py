"""二期增量路由。业务沿用一期服务，接口与前端解耦。"""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query, File, Form, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .api import admin, operate, row, as_dict, variant_dict, content_dict
from .db import get_db
from .models import (Platform, Content, ContentVariant, AIProvider, MediaAsset, AssetUsage,
                     VideoJob, WorkspaceAccount, WorkspaceJob, Topic, TopicSuggestion,
                     CommentTask, CommentAction, ReplyTemplate, DMPolicy, DMMessage)
from .phase2_schemas import (PlatformIn, BulkReviewIn, DraftIn, ProviderIn, VideoIn,
                            AccountIn, AccountLoginIn, PublishJobIn, CommentTaskIn,
                            DiscoverIn, ReplyTemplateIn, DMPolicyIn, DMIn)

api = APIRouter()


@api.get('/dashboard/platforms', tags=['二期平台'])
def platform_dashboard(db: Session = Depends(get_db), _=Depends(operate)):
    from .models import Metric, Interaction, Lead
    result = []
    for p in db.scalars(select(Platform).order_by(Platform.id)).all():
        published = db.scalar(select(func.count(ContentVariant.id)).where(ContentVariant.platform_id == p.id, ContentVariant.status == 'published'))
        views = db.scalar(select(func.coalesce(func.sum(Metric.views), 0)).join(ContentVariant, Metric.variant_id == ContentVariant.id).where(ContentVariant.platform_id == p.id))
        result.append({'platform_id': p.id, 'platform': p.code, 'name': p.name, 'enabled': p.enabled,
            'published': published, 'views': views,
            'interactions': db.scalar(select(func.count(Interaction.id)).where(Interaction.platform_id == p.id)),
            'leads': db.scalar(select(func.count(Lead.id)).where(Lead.platform_id == p.id))})
    return result


@api.get('/platforms/templates', tags=['二期平台'])
def templates(_=Depends(operate)):
    from .platforms import TEMPLATES
    return TEMPLATES


@api.get('/platforms', tags=['二期平台'])
def platforms(enabled: bool | None = None, db: Session = Depends(get_db), _=Depends(operate)):
    q = select(Platform).order_by(Platform.id)
    if enabled is not None:q=q.where(Platform.enabled == enabled)
    return [as_dict(p) for p in db.scalars(q).all()]


@api.post('/platforms', status_code=201, tags=['二期平台'])
def add_platform(body: PlatformIn, db: Session = Depends(get_db), _=Depends(admin)):
    p=Platform(**body.model_dump(exclude={'expected_version'}));db.add(p);db.commit();return as_dict(p)


@api.put('/platforms/{pid}', tags=['二期平台'])
def edit_platform(pid: int, body: PlatformIn, db: Session = Depends(get_db), _=Depends(admin)):
    p=row(db,Platform,pid,body.expected_version)
    if p.code != body.code:raise HTTPException(409,'平台code稳定不可改名；请停用后另建')
    for k,v in body.model_dump(exclude={'expected_version'}).items():setattr(p,k,v)
    db.commit();return as_dict(p)


@api.get('/variants', tags=['二期内容'])
def variants(platform_id: int | None = None, platform: str | None = None, status: str | None = None,
             confirm_status: str | None = None, scheduled_from: date | None = None, scheduled_to: date | None = None,
             min_score: int = Query(0,ge=0,le=100), max_score: int = Query(100,ge=0,le=100),
             compliance_ok: bool | None = None, current: bool = True, limit: int = Query(50,ge=1,le=200),
             offset: int = Query(0,ge=0), db: Session = Depends(get_db), _=Depends(operate)):
    q=select(ContentVariant).join(Content).where(ContentVariant.is_current == current,
        ContentVariant.quality_score>=min_score,ContentVariant.quality_score<=max_score)
    if platform_id:q=q.where(ContentVariant.platform_id==platform_id)
    if platform:q=q.where(ContentVariant.platform==platform)
    if status:q=q.where(ContentVariant.status==status)
    if confirm_status:q=q.where(ContentVariant.confirm_status==confirm_status)
    if scheduled_from:q=q.where(Content.scheduled_date>=scheduled_from)
    if scheduled_to:q=q.where(Content.scheduled_date<=scheduled_to)
    if compliance_ok is not None:q=q.where(ContentVariant.compliance_ok==compliance_ok)
    total=db.scalar(select(func.count()).select_from(q.subquery()))
    rows=db.scalars(q.order_by(ContentVariant.id.desc()).limit(limit).offset(offset)).all()
    return {'items':[{**variant_dict(v),'content_title':v.content.title,'scheduled_date':v.content.scheduled_date} for v in rows],
            'total':total,'limit':limit,'offset':offset}


@api.get('/variants/{vid}', tags=['二期内容'])
def variant(vid:int,db:Session=Depends(get_db),_=Depends(operate)):
    v=row(db,ContentVariant,vid);return {**variant_dict(v),'content_title':v.content.title,'scheduled_date':v.content.scheduled_date}


@api.post('/variants/bulk-review', tags=['二期内容'])
def bulk_review(body:BulkReviewIn,db:Session=Depends(get_db),actor=Depends(operate)):
    from .generator import approve_variant,reject_variant,apply_compliance,ensure_current,refresh_content_status
    from .tasks import lock
    ids=sorted(set(body.variant_ids))
    if body.action=='reject' and not body.reason:raise HTTPException(422,'批量驳回必须有理由')
    if set(body.expected_versions) != {str(i) for i in ids}:
        raise HTTPException(422,'批量操作须提供每条版本号，避免覆盖其他人的审核')
    values=[]
    for vid in ids:
        lock(db,f'variant-review:{vid}')
        v=row(db,ContentVariant,vid,body.expected_versions.get(str(vid)));ensure_current(v)
        if v.status=='published':raise HTTPException(409,'整批取消：包含已发布版本')
        values.append(v)
    if body.action=='approve':
        valid=[apply_compliance(db,v) and v.status=='pending' and v.quality_score>=70 for v in values]
        if not all(valid):
            db.commit();raise HTTPException(409,'整批未通过：包含合规或质检未通过版本')
    result=[]
    for v in values:
        if body.action=='approve':approve_variant(db,v,actor);result.append({'id':v.id,'approved':True})
        else:
            new=reject_variant(db,v,body.reason,actor)
            result.append({'id':v.id,'new_variant_id':new.id if new else None,'retryable':new is None})
        db.flush();refresh_content_status(db,v.content)
    db.commit();return {'processed':len(result),'items':result}


@api.post('/contents/drafts', status_code=201, tags=['二期内容'])
def draft(body:DraftIn,db:Session=Depends(get_db),_=Depends(operate)):
    from .platforms import resolve
    from .generator import apply_compliance
    p=resolve(db,platform_id=body.platform_id,enabled=True)
    assets=[row(db,MediaAsset,i) for i in set(body.asset_ids)]
    if any(a.publicity!='public' for a in assets):raise HTTPException(409,'对外内容只能引用已批准公开素材')
    c=Content(title=body.title,biz_line=body.biz_line,source='manual',scheduled_date=body.scheduled_date)
    db.add(c);db.flush()
    v=ContentVariant(content_id=c.id,platform=p.code,platform_id=p.id,body=body.body,status='draft')
    db.add(v);db.flush();apply_compliance(db,v)
    for a in assets:db.add(AssetUsage(asset_id=a.id,variant_id=v.id))
    db.commit();return content_dict(c)


@api.get('/ai/providers', tags=['二期AI'])
def providers(db:Session=Depends(get_db),_=Depends(admin)):
    from .ai_providers import public_config
    return [public_config(p) for p in db.scalars(select(AIProvider).order_by(AIProvider.priority)).all()]


@api.post('/ai/providers', status_code=201, tags=['二期AI'])
def provider_create(body:ProviderIn,db:Session=Depends(get_db),_=Depends(admin)):
    from .ai_providers import trusted_url,public_config
    data=body.model_dump(exclude={'expected_version'});data['endpoint']=trusted_url(data['endpoint'])
    p=AIProvider(**data);db.add(p);db.commit();return public_config(p)


@api.put('/ai/providers/{pid}', tags=['二期AI'])
def provider_edit(pid:int,body:ProviderIn,db:Session=Depends(get_db),_=Depends(admin)):
    from .ai_providers import trusted_url,public_config
    p=row(db,AIProvider,pid,body.expected_version);data=body.model_dump(exclude={'expected_version'});data['endpoint']=trusted_url(data['endpoint'])
    for k,v in data.items():setattr(p,k,v)
    db.commit();return public_config(p)


@api.post('/ai/providers/{pid}/test', tags=['二期AI'])
def provider_test(pid:int,db:Session=Depends(get_db),_=Depends(admin)):
    from .llm import call_json,AIUnavailable
    p=row(db,AIProvider,pid)
    if p.capability!='text':return {'ok':False,'detail':'视频提供方请通过实际任务验证，不伪造连通成功'}
    try:
        result=call_json(db,'provider_test','返回JSON {"ok":true}','连接测试',provider_id=pid)
        db.commit();return {'ok':True,'demo':__import__('app.config',fromlist=['DEMO_MODE']).DEMO_MODE,'result':result}
    except AIUnavailable:
        db.commit();return {'ok':False,'detail':'连接失败或未配置环境密钥，详见AI日志'}


@api.get('/topic-suggestions', tags=['需求反哺'])
def suggestions(db:Session=Depends(get_db),_=Depends(operate)):
    return [as_dict(s) for s in db.scalars(select(TopicSuggestion).order_by(TopicSuggestion.id.desc()).limit(200)).all()]


@api.post('/topic-suggestions/{sid}/convert', tags=['需求反哺'])
def convert_suggestion(sid:int,db:Session=Depends(get_db),_=Depends(operate)):
    from .tasks import lock
    lock(db,f'suggestion:{sid}');s=row(db,TopicSuggestion,sid)
    if not s.topic_id:
        t=Topic(title=s.title,biz_line=s.biz_line,theme='客户需求',angle=s.need);db.add(t);db.flush();s.topic_id=t.id;db.commit()
    return {'topic_id':s.topic_id,'suggestion_id':s.id}

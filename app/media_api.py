from typing import Literal
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session
from .api import operate, row, as_dict
from .db import get_db
from .models import MediaAsset, AssetUsage, VideoJob, AIProvider, Content, ContentVariant, Topic
from .phase2_schemas import VideoIn, AssetUpdate, AssetGenerateIn, AssetLinkIn
from . import storage
from .tasks import lock

api = APIRouter()


@api.post('/assets/upload', status_code=201, tags=['二期素材'])
def upload(files: list[UploadFile] = File(...), publicity: Literal['public','internal','masked'] = Form('internal'),
           tags: str = Form('', max_length=500), category: str = Form('', max_length=100),
           db: Session = Depends(get_db), actor=Depends(operate)):
    from .media import clean_image, save_asset
    from . import config
    if not 1 <= len(files) <= 20:
        raise HTTPException(422, '每批1至20张图片')
    # 整批先验证，禁止部分坏图导致部分业务入库。
    images = [(f.filename or '公司图片', clean_image(f.file.read(config.UPLOAD_MAX_BYTES+1))) for f in files]
    result = [as_dict(save_asset(db, data, kind='image', title=name, content_type='image/png',
              publicity=publicity, tags=tags, category=category, creator_id=actor.id)) for name,data in images]
    db.commit()
    return {'items':result}


@api.get('/assets', tags=['二期素材'])
def assets(kind: str | None = None, publicity: str | None = None, category: str | None = None,
           tag: str | None = None, limit: int = Query(50,ge=1,le=200), offset: int = Query(0,ge=0),
           db:Session=Depends(get_db),_=Depends(operate)):
    q=select(MediaAsset).order_by(MediaAsset.id.desc())
    for field,value in [('kind',kind),('publicity',publicity),('category',category)]:
        if value:q=q.where(getattr(MediaAsset,field)==value)
    if tag:q=q.where(MediaAsset.tags.contains(tag, autoescape=True))
    return [as_dict(a) for a in db.scalars(q.limit(limit).offset(offset)).all()]


@api.put('/assets/{aid}', tags=['二期素材'])
def edit_asset(aid:int,body:AssetUpdate,db:Session=Depends(get_db),_=Depends(operate)):
    a=row(db,MediaAsset,aid,body.expected_version)
    for k,v in body.model_dump(exclude={'expected_version'}).items():setattr(a,k,v)
    db.commit();return as_dict(a)


@api.get('/assets/{aid}/url', tags=['二期素材'])
def asset_url(aid:int,db:Session=Depends(get_db),_=Depends(operate)):
    return {'url':storage.signed_url(row(db,MediaAsset,aid).object_ref),'expires_seconds':600}


@api.get('/assets/{aid}/usage', tags=['二期素材'])
def usage(aid:int,db:Session=Depends(get_db),_=Depends(operate)):
    row(db,MediaAsset,aid)
    return [as_dict(a) for a in db.scalars(select(AssetUsage).where(AssetUsage.asset_id==aid)).all()]


@api.post('/variants/{vid}/assets', tags=['二期素材'])
def link_assets(vid:int,body:AssetLinkIn,db:Session=Depends(get_db),_=Depends(operate)):
    from .generator import ensure_current
    v=row(db,ContentVariant,vid,body.expected_version);ensure_current(v)
    if v.status=='published':raise HTTPException(409,'已发布版本不能换素材')
    selected=[row(db,MediaAsset,i) for i in set(body.asset_ids)]
    if any(a.publicity!='public' for a in selected):raise HTTPException(409,'只能引用已批准公开素材')
    for a in selected:
        if not db.scalar(select(AssetUsage.id).where(AssetUsage.asset_id==a.id,AssetUsage.variant_id==v.id)):
            db.add(AssetUsage(asset_id=a.id,variant_id=v.id))
    v.confirm_status='none'
    db.commit();return {'asset_ids':[a.id for a in selected],'review_required':True}


@api.post('/assets/generate-content', status_code=201, tags=['二期素材'])
def generate_content(body:AssetGenerateIn,db:Session=Depends(get_db),_=Depends(operate)):
    import json
    from .platforms import resolve
    from .generator import generation_context, build_variant, SYS
    from .llm import call_json
    topic=row(db,Topic,body.topic_id)
    platform=resolve(db,platform_id=body.platform_id,enabled=True)
    assets=[row(db,MediaAsset,i) for i in sorted(set(body.asset_ids))]
    if any(a.publicity!='public' for a in assets):raise HTTPException(409,'私有或未脱敏素材不得发送AI')
    lock(db,'asset-generation:'+body.request_key)
    existing=db.scalar(select(Content).where(Content.generation_key=='assets:'+body.request_key))
    if existing:
        current = db.scalar(select(ContentVariant).where(ContentVariant.content_id == existing.id, ContentVariant.is_current.is_(True)))
        linked = set(db.scalars(select(AssetUsage.asset_id).where(AssetUsage.variant_id == current.id)).all()) if current else set()
        if existing.topic_id != topic.id or not current or current.platform_id != platform.id or linked != {a.id for a in assets} or existing.scheduled_date != body.scheduled_date:
            raise HTTPException(409, '幂等键已被不同的素材生成请求使用')
        from .api import content_dict
        return content_dict(existing)
    context=generation_context(db,topic)
    context.update(platform=platform.code,reason='按所选素材信息生成',assets=[{'title':a.title,'category':a.category,'tags':a.tags} for a in assets])
    data=call_json(db,'regenerate',SYS+'\n只返回当前platform的单个版本对象。图片仅提供人工确认的标题/标签信息，未读取图片像素，不得编造图中细节。',
                   json.dumps(context,ensure_ascii=False),topic.id,context)
    c=Content(topic_id=topic.id,biz_line=topic.biz_line,title=topic.title,scheduled_date=body.scheduled_date,generation_key='assets:'+body.request_key)
    db.add(c);db.flush()
    v=build_variant(db,c,platform.code,data)
    for a in assets:db.add(AssetUsage(asset_id=a.id,variant_id=v.id))
    db.commit()
    from .api import content_dict
    return content_dict(c)


@api.post('/video-jobs', status_code=201, tags=['二期视频'])
def create_video(body:VideoIn,db:Session=Depends(get_db),_=Depends(operate)):
    from .platforms import resolve
    lock(db,'video-key:'+body.request_key)
    existing=db.scalar(select(VideoJob).where(VideoJob.request_key==body.request_key))
    if existing:
        if any(getattr(existing,k)!=v for k,v in body.model_dump().items() if k!='provider_id'):
            raise HTTPException(409,'幂等键已被不同任务使用')
        return as_dict(existing)
    if body.platform_id:resolve(db,platform_id=body.platform_id,enabled=True)
    if body.image_asset_id:
        a=row(db,MediaAsset,body.image_asset_id)
        if a.kind!='image' or a.publicity!='public':raise HTTPException(409,'图生视频仅可使用已批准公开的图片')
    if body.provider_id:
        p=row(db,AIProvider,body.provider_id)
        if not p.enabled or p.capability!='video':raise HTTPException(422,'提供方不是启用的视频服务')
    job=VideoJob(**body.model_dump());db.add(job);db.commit();return as_dict(job)


@api.get('/video-jobs', tags=['二期视频'])
def videos(db:Session=Depends(get_db),_=Depends(operate)):
    return [as_dict(j) for j in db.scalars(select(VideoJob).order_by(VideoJob.id.desc()).limit(200)).all()]


@api.get('/video-jobs/{jid}', tags=['二期视频'])
def video(jid:int,db:Session=Depends(get_db),_=Depends(operate)):
    return as_dict(row(db,VideoJob,jid))


@api.post('/video-jobs/{jid}/run', tags=['二期视频'])
def run_video(jid:int,db:Session=Depends(get_db),_=Depends(operate)):
    from .media import run_video
    return as_dict(run_video(db,row(db,VideoJob,jid)))


@api.post('/video-jobs/{jid}/retry', tags=['二期视频'])
def retry_video(jid:int,db:Session=Depends(get_db),_=Depends(operate)):
    from .media import run_video
    return as_dict(run_video(db,row(db,VideoJob,jid),retry=True))

"""数据表驱动平台；code兼容一期，platform_id为统一关联键。"""
from sqlalchemy import select
from fastapi import HTTPException
from .models import Platform

TEMPLATES = [
 {'code':'douyin','name':'抖音','category':'video','style_prompt':'60秒口播，按实际场景表达，保留必要口径'},
 {'code':'shipinhao','name':'视频号','category':'video','style_prompt':'稳健的行业经验分享'},
 {'code':'gzh','name':'公众号','category':'text','style_prompt':'结构化深度图文，事实可追溯'},
 {'code':'moments','name':'朋友圈','category':'text','style_prompt':'3-5行销售可转发短文'},
 {'code':'taobao','name':'淘宝','category':'commerce','style_prompt':'产品特点、规格及服务边界，禁止虚假承诺'},
 {'code':'xhs','name':'小红书','category':'text','style_prompt':'真实使用场景与实用建议'},
 {'code':'kuaishou','name':'快手','category':'video','style_prompt':'简明口语化演示，真实产品信息'},
 {'code':'bilibili','name':'B站','category':'video','style_prompt':'技术讲解和步骤演示，注明适用边界'},
]


def seed_platforms(db):
    for data in TEMPLATES[:4]:
        if not db.scalar(select(Platform).where(Platform.code == data['code'])):
            db.add(Platform(**data))
    db.flush()


def resolve(db, code=None, platform_id=None, enabled=False):
    platform = db.get(Platform, platform_id) if platform_id else db.scalar(select(Platform).where(Platform.code == code))
    if not platform or platform.deleted_at or (enabled and not platform.enabled):
        raise HTTPException(422, '平台不存在或已停用')
    if code and platform.code != code:
        raise HTTPException(422, 'platform与platform_id不匹配')
    return platform


def active(db):
    return db.scalars(select(Platform).where(Platform.enabled.is_(True), Platform.generation_enabled.is_(True)).order_by(Platform.id)).all()

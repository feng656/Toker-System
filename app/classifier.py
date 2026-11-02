"""评论/私信 AI 打标：身份(工程商/甲方) × 意向(high/mid/low/junk) + 线索提取。"""
import json

from sqlalchemy.orm import Session

from .llm import chat_json
from .models import Interaction, Lead

SYS = """你是B2B弱电智能化行业的销售线索助手。分析一条用户评论/私信，输出JSON：
{"identity":"contractor(工程商,如出现'我们有个项目''甲方要求''投标''安装队')或owner(甲方,如'我们单位要建''采购')或unknown",
 "intent":"high(询价/求联系方式/有项目要合作/问能否配合投标/问地州能否送货安装)或mid(问参数型号工期品牌)或low(纯互动)或junk(广告)",
 "need_summary":"一句话需求摘要含项目类型地区", "contact_info":"提取到的微信号/手机号，无则空",
 "brand_need":"提及的品牌或产品", "reply_suggestion":"一句回复话术。口径：渠道线强调总代现货库存+不抢甲方客户；项目线强调案例与全省服务。禁止出现任何价格数字。"}
只输出JSON。"""


def classify_interaction(db: Session, it: Interaction) -> Lead:
    data = chat_json(SYS, f"平台:{it.platform} 类型:{it.kind}\n内容:{it.body}")
    lead = Lead(
        interaction_id=it.id, platform=it.platform,
        visitor_name=it.author_name,
        intent=data.get("intent", "low"),
        identity=data.get("identity", "unknown"),
        need_summary=data.get("need_summary", ""),
        contact_info=data.get("contact_info", ""),
        brand_need=data.get("brand_need", ""),
        reply_suggestion=data.get("reply_suggestion", ""),
        status="new",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    if lead.intent == "high":
        from .notify import push_lead
        push_lead(lead)
    return lead


def classify_text(db: Session, platform: str, kind: str,
                  author_name: str, body: str) -> Lead:
    it = Interaction(platform=platform, kind=kind,
                     author_name=author_name, body=body)
    db.add(it)
    db.commit()
    db.refresh(it)
    return classify_interaction(db, it)

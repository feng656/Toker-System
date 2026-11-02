"""发布执行器：公众号 / 抖音企业号 官方API自动发布。
凭据存 platform_accounts 表，一次性配置，token 自动续期。
"""
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ContentVariant, PlatformAccount


# ---------- 公众号 ----------

def _gzh_token(db: Session) -> str | None:
    acc = db.scalar(select(PlatformAccount).where(
        PlatformAccount.platform == "gzh", PlatformAccount.enabled.is_(True)))
    if not acc or not acc.appid:
        return None
    if acc.access_token and acc.token_expires_at and \
            acc.token_expires_at > datetime.now() + timedelta(minutes=5):
        return acc.access_token
    r = httpx.get("https://api.weixin.qq.com/cgi-bin/token", params={
        "grant_type": "client_credential",
        "appid": acc.appid, "secret": acc.appsecret,
    }, timeout=15).json()
    if "access_token" not in r:
        return None
    acc.access_token = r["access_token"]
    acc.token_expires_at = datetime.now() + timedelta(seconds=r["expires_in"] - 300)
    db.commit()
    return acc.access_token


def publish_gzh(db: Session, v: ContentVariant) -> dict:
    """草稿箱 → 发布。返回 {ok, url/err}。"""
    token = _gzh_token(db)
    if not token:
        return {"ok": False, "err": "公众号未配置凭据或token获取失败"}
    # 1. 建草稿
    draft = httpx.post(
        f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}",
        json={"articles": [{
            "title": (v.cover_text or v.body[:30])[:64],
            "author": "云南自由光科技",
            "content": v.body.replace("\n", "<br/>"),
            "digest": v.body[:120],
            "need_open_comment": 1,
        }]}, timeout=20).json()
    media_id = draft.get("media_id")
    if not media_id:
        return {"ok": False, "err": f"草稿失败: {draft}"}
    # 2. 发布（submit，微信异步推送给关注者）
    pub = httpx.post(
        f"https://api.weixin.qq.com/cgi-bin/freepublish/submit?access_token={token}",
        json={"media_id": media_id}, timeout=20).json()
    if pub.get("errcode", 0) == 0:
        return {"ok": True, "publish_id": pub.get("publish_id"),
                "url": f"gzh:media_id={media_id}"}
    return {"ok": False, "err": f"发布失败: {pub}"}


# ---------- 抖音企业号 ----------

def _douyin_token(db: Session) -> str | None:
    acc = db.scalar(select(PlatformAccount).where(
        PlatformAccount.platform == "douyin", PlatformAccount.enabled.is_(True)))
    if not acc:
        return None
    # 抖音用 client_token + 授权 open_id 体系；若已存 access_token 直接用
    if acc.access_token and acc.token_expires_at and \
            acc.token_expires_at > datetime.now() + timedelta(minutes=5):
        return acc.access_token
    if acc.appid and acc.appsecret:
        r = httpx.post("https://open.douyin.com/oauth/client_token/",
                       data={"client_key": acc.appid,
                             "client_secret": acc.appsecret,
                             "grant_type": "client_credential"},
                       timeout=15).json()
        tok = (r.get("data") or {}).get("access_token")
        if tok:
            acc.access_token = tok
            acc.token_expires_at = datetime.now() + timedelta(
                seconds=(r["data"].get("expires_in", 7200) - 300))
            db.commit()
            return tok
    return None


def publish_douyin(db: Session, v: ContentVariant) -> dict:
    """抖音图文/视频发布。视频需先上传素材，此版本走图文+后续扩展。"""
    acc = db.scalar(select(PlatformAccount).where(
        PlatformAccount.platform == "douyin", PlatformAccount.enabled.is_(True)))
    open_id = (acc.extra or {}).get("open_id") if acc else None
    token = _douyin_token(db)
    if not token or not open_id:
        return {"ok": False, "err": "抖音企业号未完成授权（需open_id+access_token）"}
    r = httpx.post("https://open.douyin.com/video/create/",
                   headers={"access-token": token},
                   data={"open_id": open_id, "text": v.body[:2200]},
                   timeout=20).json()
    if (r.get("data") or {}).get("error_code") == 0:
        return {"ok": True, "url": f"douyin:item={r['data'].get('item_id','')}"}
    return {"ok": False, "err": str(r)[:300]}


# ---------- 统一入口 ----------

PUBLISHERS = {"gzh": publish_gzh, "douyin": publish_douyin}


def publish_variant(db: Session, v: ContentVariant) -> dict:
    fn = PUBLISHERS.get(v.platform)
    if not fn:
        return {"ok": False, "err": f"{v.platform} 暂无自动发布通道（请人工复制发布）"}
    v.publish_status = "publishing"
    db.commit()
    r = fn(db, v)
    if r["ok"]:
        v.publish_status = "published"
        v.published_url = r.get("url", "")
        v.published_at = datetime.now()
    else:
        v.publish_status = "failed"
        v.publish_error = r["err"][:500]
    db.commit()
    return r

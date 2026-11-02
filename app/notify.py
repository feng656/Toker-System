"""企业微信机器人推送：高意向线索 / 待办催办。"""
import json
import urllib.request

from .config import WECOM_WEBHOOK


def _post(payload: dict) -> bool:
    if not WECOM_WEBHOOK:
        return False
    try:
        req = urllib.request.Request(
            WECOM_WEBHOOK,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def send_text(msg: str) -> bool:
    return _post({"msgtype": "text", "text": {"content": msg}})


def push_lead(lead) -> bool:
    identity = {"contractor": "工程商", "owner": "甲方", "unknown": "未知"}.get(lead.identity, "未知")
    msg = (
        f"🔥 高意向线索 #{lead.id}\n"
        f"平台：{lead.platform}｜身份：{identity}\n"
        f"访客：{lead.visitor_name}\n"
        f"需求：{lead.need_summary}\n"
        f"联系方式：{lead.contact_info or '未留'}\n"
        f"建议话术：{lead.reply_suggestion}"
    )
    return send_text(msg)


def remind_confirm(n: int, top: str = "") -> bool:
    return send_text(f"✅ {n} 条内容已通过AI质检，等你点「确认发布」。\n最新：{top}")


def remind_todo(pending: int) -> bool:
    return send_text(f"📋 今日还有 {pending} 条内容待发布/待回填，请到拓客系统「今日待办」处理。")

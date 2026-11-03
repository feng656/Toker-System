"""事务型outbox。至少一次投递；CRM接收端按Idempotency-Key幂等。"""
from datetime import timedelta
import httpx
from sqlalchemy import or_, select
from . import config
from .db import utcnow
from .models import Outbox
from .tasks import lock


def enqueue(db, channel, event_key, payload, lead_id=None):
    key = f'{channel}:{event_key}'
    lock(db, key)
    event = db.scalar(select(Outbox).where(Outbox.event_key == key))
    if not event:
        event = Outbox(channel=channel, event_key=key, payload=payload,
                       lead_id=lead_id, next_attempt_at=utcnow())
        db.add(event)
        db.flush()
    return event


def enqueue_lead(db, lead, reason):
    payload = {'lead_id': lead.id, 'intent': lead.intent, 'identity': lead.identity,
               'visitor_name': lead.visitor_name, 'platform': lead.platform,
               'need_summary': lead.need_summary, 'contact_info': lead.contact_info,
               'assignee': lead.assignee, 'status': lead.status,
               'reply_suggestion': lead.reply_suggestion}
    return [enqueue(db, channel, f'lead:{lead.id}:{reason}', payload, lead.id)
            for channel in ('wecom', 'crm')]


def deliver(db, event):
    lock(db, f'outbox:{event.id}')
    db.refresh(event)
    if event.status in ('sent', 'dead'):
        return event
    event.attempts += 1
    try:
        url = config.WECOM_WEBHOOK if event.channel == 'wecom' else config.CRM_WEBHOOK
        if not url:
            raise ValueError('目标通道未配置，请配置后人工重试')
        headers = {'Idempotency-Key': event.event_key}
        if event.channel == 'crm' and config.CRM_TOKEN:
            headers['Authorization'] = 'Bearer ' + config.CRM_TOKEN
        payload = event.payload
        if event.channel == 'wecom':
            p = event.payload
            message = p.get('message') or (f"线索 #{p.get('lead_id')}｜{p.get('intent')}｜{p.get('platform')}\n"
                  f"需求：{p.get('need_summary')}\n联系方式：{p.get('contact_info') or '未留'}\n负责人：{p.get('assignee') or '待指派'}")
            payload = {'msgtype': 'text', 'text': {'content': message[:2000]}}
        r = httpx.post(url, json=payload, headers=headers, timeout=10, follow_redirects=False)
        r.raise_for_status()
        result = r.json() if r.content else {}
        if event.channel == 'wecom' and result.get('errcode') != 0:
            raise ValueError('企微业务拒绝，错误码：' + str(result.get('errcode')))
        if event.channel == 'crm' and (result.get('ok') is False or result.get('success') is False):
            raise ValueError('CRM业务返回失败')
        event.status, event.last_error, event.response = 'sent', '', {'http_status': r.status_code}
        event.sent_at, event.next_attempt_at = utcnow(), None
    except Exception as exc:
        event.status = 'dead' if event.attempts >= config.OUTBOX_MAX_ATTEMPTS else 'failed'
        event.last_error = str(exc)[:500] if isinstance(exc, ValueError) else type(exc).__name__ + ': 通道请求失败'
        event.next_attempt_at = utcnow() + timedelta(seconds=min(3600, 30 * 2 ** (event.attempts - 1))) if event.status != 'dead' else None
    db.flush()
    return event


def process_due(db, limit=50):
    rows = db.scalars(select(Outbox).where(Outbox.status.in_(['pending', 'failed']),
          or_(Outbox.next_attempt_at.is_(None), Outbox.next_attempt_at <= utcnow()))
          .order_by(Outbox.id).limit(limit).with_for_update(skip_locked=True)).all()
    for event in rows:
        deliver(db, event)
    db.commit()
    return len(rows)


def retry_event(db, event):
    if event.status == 'sent':
        return event
    # 人工复活死信开启新一轮上限；保留总attempts，单次重试后仍失败会再次死信。
    event.status, event.next_attempt_at = 'pending', utcnow()
    db.flush()
    return deliver(db, event)

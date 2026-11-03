"""截图识别 -> pending_review -> 显式字段确认 -> 业务落库，永不自动入指标。"""
import hashlib
import io
import re
from datetime import date
from PIL import Image, UnidentifiedImageError
import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from . import config, storage
from .db import utcnow
from .models import ContentVariant, Interaction, Metric, OCRTask
from .schemas import InteractionIn, MetricIn
from .tasks import lock

METRIC_FIELDS = ['views', 'likes', 'comments', 'collects', 'shares', 'new_fans', 'dm_inquiries']
LABELS = {'views': ['曝光', '播放', '阅读', 'views'], 'likes': ['点赞', 'likes'],
          'comments': ['评论', 'comments'], 'collects': ['收藏', 'collects'],
          'shares': ['分享', '转发', 'shares'], 'new_fans': ['新增粉丝', '涨粉', 'new_fans'],
          'dm_inquiries': ['私信咨询', '私信', 'dm_inquiries']}


def validate_image(data):
    if not data or len(data) > config.UPLOAD_MAX_BYTES:
        raise HTTPException(413, '截图为空或超过大小限制')
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in ('PNG', 'JPEG', 'WEBP') or img.width * img.height > 25_000_000:
                raise ValueError('图片格式或尺寸不支持')
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(422, '请上传有效PNG/JPEG/WEBP截图')


def parse_text(text, kind, confidence=0.0):
    if kind == 'comments':
        comments = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            author, sep, body = line.partition('：')
            if not sep:
                author, sep, body = line.partition(':')
            comments.append({'author_name': author.strip() if sep else '',
                             'author_id': '', 'body': body.strip() if sep else line, 'kind': 'comment'})
        return {'comments': comments[:100]}, {'comments': confidence}
    fields, conf = {}, {}
    for name, labels in LABELS.items():
        match = re.search(r'(?:' + '|'.join(labels) + r')\s*[:：]?\s*([\d,]+(?:\.\d+)?)\s*([万亿wWkK]?)', text, re.I)
        if match:
            factor = {'万': 10000, '亿': 100000000, 'w': 10000, 'k': 1000}.get(match[2].lower(), 1)
            fields[name] = int(float(match[1].replace(',', '')) * factor)
            conf[name] = confidence
        else:
            fields[name], conf[name] = 0, 0.0  # 缺失值0必须被人工确认，不能默认为可信。
    fields['stat_date'], conf['stat_date'] = str(date.today()), 0.0
    return fields, conf


def recognize(data, kind):
    if config.OCR_BACKEND == 'http':
        if not config.OCR_ENDPOINT:
            raise RuntimeError('OCR_ENDPOINT未配置')
        headers = {'Authorization': 'Bearer ' + config.OCR_TOKEN} if config.OCR_TOKEN else {}
        r = httpx.post(config.OCR_ENDPOINT, files={'file': ('screenshot.png', data, 'image/png')},
                       data={'kind': kind}, headers=headers, timeout=config.OCR_TIMEOUT, follow_redirects=False)
        r.raise_for_status()
        payload = r.json()
        raw = str(payload.get('text', ''))
        fields = payload.get('fields')
        confidence = payload.get('confidence', {})
        if not isinstance(fields, dict):
            fields, confidence = parse_text(raw, kind, float(payload.get('score', 0)))
        return raw, fields, confidence
    if config.OCR_BACKEND != 'tesseract':
        raise RuntimeError('不支持的OCR_BACKEND')
    import pytesseract
    img = Image.open(io.BytesIO(data))
    result = pytesseract.image_to_data(img, lang=config.OCR_LANG,
                        output_type=pytesseract.Output.DICT, timeout=config.OCR_TIMEOUT)
    lines, scores = {}, []
    for i, word in enumerate(result['text']):
        if not word.strip():
            continue
        key = (result['block_num'][i], result['par_num'][i], result['line_num'][i])
        lines.setdefault(key, []).append(word)
        scores.append(max(0, float(result['conf'][i])) / 100)
    raw = '\n'.join(' '.join(words) for words in lines.values())
    score = min(scores) if scores else 0.0
    fields, conf = parse_text(raw, kind, score)
    return raw, fields, conf


def apply_recognition(task, data):
    try:
        task.raw_text, task.fields, task.confidence = recognize(data, task.kind)
        expected = METRIC_FIELDS + ['stat_date'] if task.kind == 'metrics' else ['comments']
        # HTTP适配只返回部分字段时，缺失字段同样需要人工确认，不能隐式补零。
        task.low_confidence_fields = [k for k in expected if k not in task.fields or
                                      float(task.confidence.get(k, 0)) < config.OCR_THRESHOLD]
        task.error = ''
    except Exception as exc:
        task.raw_text, task.fields, task.confidence = '', {}, {}
        task.low_confidence_fields = METRIC_FIELDS + ['stat_date'] if task.kind == 'metrics' else ['comments']
        task.error = type(exc).__name__ + ': OCR未完成，请修正配置后重试或人工校录'
    task.status = 'pending_review'


def create_task(db, data, filename, kind, variant_id, platform='', request_key=None):
    if kind not in ('metrics', 'comments'):
        raise HTTPException(422, 'kind须为metrics或comments')
    validate_image(data)
    v = db.get(ContentVariant, variant_id) if variant_id else None
    if variant_id and (not v or v.deleted_at):
        raise HTTPException(404, '内容版本不存在')
    if kind == 'metrics' and not v:
        raise HTTPException(422, '指标截图必须指定内容版本')
    if not v and platform not in ('douyin', 'shipinhao', 'gzh', 'moments', 'xhs'):
        raise HTTPException(422, '评论截图须指定平台或内容版本')
    digest = hashlib.sha256(data).hexdigest()
    key = request_key or f'{kind}:{variant_id}:{platform}:{digest}'
    if len(key) > 200:
        raise HTTPException(422, '幂等键过长')
    lock(db, f'ocr:{key}')
    old = db.scalar(select(OCRTask).where(OCRTask.request_key == key))
    if old:
        return old
    try:
        ref = storage.put(data, filename, 'image/png')
    except Exception:
        raise HTTPException(503, '截图未保存：对象存储未配置或不可用')
    task = OCRTask(request_key=key, kind=kind, variant_id=variant_id,
                   platform=v.platform if v else platform, image_url=ref)
    db.add(task)
    apply_recognition(task, data)
    db.flush()
    return task


def save_metric(db, payload, actor_id, source='manual', ocr_task=None):
    v = db.get(ContentVariant, payload.variant_id)
    if not v or v.deleted_at:
        raise HTTPException(404, '内容版本不存在')
    if v.status != 'published' or not v.published_url:
        raise HTTPException(409, '未回填真实链接的内容不能录入发布指标')
    lock(db, f'metric:{payload.variant_id}:{payload.stat_date}')
    metric = db.scalar(select(Metric).where(Metric.variant_id == payload.variant_id,
                      Metric.stat_date == payload.stat_date))
    if not metric:
        metric = Metric(variant_id=payload.variant_id, stat_date=payload.stat_date)
        db.add(metric)
    for k, value in payload.model_dump().items():
        setattr(metric, k, value)
    metric.source, metric.confirmed_by = source, actor_id
    if ocr_task:
        metric.ocr_task_id, metric.raw_img_url = ocr_task.id, ocr_task.image_url
    db.flush()
    return metric


def confirm_task(db, task, body, actor):
    lock(db, f'ocr-confirm:{task.id}')
    db.refresh(task)
    if task.status == 'confirmed':
        if task.confirmed_payload != body.data:
            raise HTTPException(409, '该截图已确认，不能用不同数据重复确认')
        return task
    missing = set(task.low_confidence_fields) - (set(body.confirmed_fields) & set(body.data))
    if missing:
        raise HTTPException(422, '以下低置信字段必须逐项校对确认：' + ','.join(sorted(missing)))
    if task.kind == 'metrics':
        try:
            data = dict(body.data)
            if 'variant_id' in data and data['variant_id'] != task.variant_id:
                raise HTTPException(422, '不能更改截图关联版本')
            data['variant_id'] = task.variant_id
            metric = MetricIn.model_validate(data)
        except ValidationError as exc:
            raise HTTPException(422, str(exc))
        row = save_metric(db, metric, actor.id, 'ocr', task)
        task.result = {'metric_id': row.id}
    else:
        comments = body.data.get('comments')
        if not isinstance(comments, list) or not 1 <= len(comments) <= 100:
            raise HTTPException(422, 'comments须包含1-100条经校对评论')
        validated = []
        for item in comments:
            if not isinstance(item, dict):
                raise HTTPException(422, '评论必须为对象')
            try:
                validated.append(InteractionIn.model_validate({**item, 'platform': task.platform,
                                      'variant_id': task.variant_id}))
            except ValidationError as exc:
                raise HTTPException(422, str(exc))
        from .classifier import classify_interaction
        ids, lead_ids = [], []
        for i, item in enumerate(validated):
            it = Interaction(**item.model_dump(exclude={'auto_classify', 'source_key'}),
                             source_key=f'ocr:{task.id}:{i}', body_img_url=task.image_url, ocr_task_id=task.id)
            db.add(it)
            db.flush()
            lead = classify_interaction(db, it)
            ids.append(it.id)
            if lead:
                lead_ids.append(lead.id)
        task.result = {'interaction_ids': ids, 'lead_ids': sorted(set(lead_ids))}
    task.status, task.confirmed_by, task.confirmed_at = 'confirmed', actor.id, utcnow()
    task.confirmed_payload = body.data
    db.flush()
    return task

"""有界超时、逐次调用留痕。未配置时明确失败，不把占位结果冒充生产输出。"""
import hashlib
import json
import re
import time
import httpx
from sqlalchemy.orm import Session
from . import config
from .models import AIJob


class AIUnavailable(RuntimeError):
    pass


def _demo(kind, context):
    """仅显式 DEMO_MODE 下使用的确定性验收数据。"""
    if kind == 'quality':
        return {'score': 90, 'note': '演示评审；生产须由真实AI评估', 'issues': []}
    if kind == 'classify':
        body = context.get('body', '')
        phone = re.search(r'(?<!\d)1[3-9]\d{9}(?!\d)', re.sub(r'[\s-]', '', body))
        wx = re.search(r'(?:微信|wechat|wx)[:：\s]*([a-zA-Z][\w-]{5,19})', body, re.I)
        return {'identity': 'contractor' if any(t in body for t in ('工程', '投标', '安装队')) else 'owner' if any(t in body for t in ('单位', '采购')) else 'unknown',
                'intent': 'high' if any(t in body for t in ('询价', '报价', '项目', '电话', '微信', '合作', '送货')) else 'mid' if '型号' in body else 'low',
                'need_summary': body[:500], 'contact_info': phone.group() if phone else wx.group(1) if wx else '',
                'brand_need': 'LED' if 'LED' in body.upper() else '',
                'reply_suggestion': '可私信说明项目需求和交付地区，我们提供正品现货与技术支持。'}
    if kind == 'weekly':
        return {'report_md': '## 演示周报\n数据以看板为准。演示模式未调用外部AI。'}
    topic = context.get('title', 'LED项目方案')
    required = context.get('required', ['私信询价'])
    reason = context.get('reason', '')
    def variant(platform):
        return {'body': f'【演示文案·{platform}】{topic}。按项目场景核对选型、交付和技术服务能力。{("本版根据审核意见调整：" + reason) if reason else ""}。' + '，'.join(required),
                'cover_text': topic[:150], 'hashtags': '#弱电 #项目交付', 'best_time': '18:00-20:00',
                'image_prompt': '使用已经授权的产品或案例实拍'}
    if kind == 'regenerate':
        return variant(context['platform'])
    if kind in ('comment_write', 'comment_polish'):
        return {'comments': [f'关于{context.get("keyword", "项目")}，{context.get("target_id", "目标")}的第{i+1}点讨论：{context.get("draft") or "请问有哪些实际应用经验"}？' for i in range(context.get('count',1))]}
    if kind == 'dm_reply':
        return {'reply': '感谢你的咨询，请补充项目场景和交付地区，我们由专人核实需求后回复。'}
    return {pf: variant(pf) for pf in [p['code'] for p in context.get('platforms', [])] or ('douyin', 'shipinhao', 'gzh', 'moments')}


def call_json(db: Session, kind: str, system: str, user: str,
              resource_id=None, context=None, provider_id=None) -> dict:
    context = context or {}
    digest = hashlib.sha256((system + user).encode()).hexdigest()
    from .ai_providers import text_providers
    providers = text_providers(db, provider_id)
    if config.DEMO_MODE:
        providers = [{'name': 'demo', 'model': 'deterministic-fixture', 'demo': True}]
    if not providers:
        audit = dict(kind=kind, resource_id=resource_id, input_hash=digest,
                     status='failed', error='未配置AI服务，需配置LLM_PROVIDERS或显式启用演示模式')
        db.add(AIJob(**audit))
        if 'ai_audit' in db.info:
            db.info['ai_audit'].append(audit)
        db.flush()
        raise AIUnavailable('未配置AI服务')
    errors = []
    for p in providers[:3]:
        job = AIJob(kind=kind, resource_id=resource_id, input_hash=digest,
                    provider=p.get('name', 'configured'), model=p.get('model', ''),
                    demo=bool(p.get('demo')))
        db.add(job)
        db.flush()
        start = time.monotonic()
        try:
            if p.get('demo'):
                data = _demo(kind, context)
            else:
                r = httpx.post(p['base_url'].rstrip('/') + '/chat/completions',
                               headers={'Authorization': 'Bearer ' + p['key']},
                               json={'model': p['model'], 'messages': [
                                   {'role': 'system', 'content': system},
                                   {'role': 'user', 'content': user}],
                                     'response_format': {'type': 'json_object'}},
                               timeout=config.LLM_TIMEOUT, follow_redirects=False)
                r.raise_for_status()
                raw = r.json()['choices'][0]['message']['content']
                raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip())
                data = json.loads(raw)
            if not isinstance(data, dict) or not data:
                raise ValueError('AI必须返回非空JSON对象')
            job.status, job.output = 'succeeded', data
            return data
        except Exception as exc:
            # 不记录可能携带API凭据/URL查询参数的异常正文。
            job.status = 'failed'
            job.error = type(exc).__name__ + ': AI请求失败或返回结构无效'
            errors.append(job.error)
        finally:
            job.duration_ms = int((time.monotonic() - start) * 1000)
            if 'ai_audit' in db.info:
                db.info['ai_audit'].append({name: getattr(job, name) for name in (
                    'kind', 'resource_id', 'status', 'provider', 'model', 'demo',
                    'input_hash', 'output', 'error', 'duration_ms')})
            db.flush()
    raise AIUnavailable('; '.join(errors))


def status():
    return {'demo': config.DEMO_MODE, 'configured': bool(config.LLM_PROVIDERS),
            'providers': [{'name': p.get('name', ''), 'model': p.get('model', '')}
                          for p in config.LLM_PROVIDERS]}

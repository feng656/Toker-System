"""九步可重复API演示。默认内存隔离；configured使用显式配置的开发库/真实对象存储。
失败输出步骤、脱敏请求、响应及当前数据状态，不静默吞错。
"""
import argparse
from contextlib import ExitStack
from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['isolated', 'configured'], default='isolated')
    parser.add_argument('--out', default='reports/e2e-demo.json')
    args = parser.parse_args()
    if args.mode == 'isolated':
        os.environ.update(APP_ENV='test', DATABASE_URL='sqlite:///:memory:',
            JWT_SECRET='isolated-demo-secret-not-production-0123456789', DEMO_MODE='true', SCHEDULER_ENABLED='false')
    else:
        # 必须由操作者显式选择开发配置；不允许在生产库演示。
        from app import config
        if config.APP_ENV not in ('development', 'test') or not config.DEMO_MODE:
            raise SystemExit('configured演示要求专用开发环境且DEMO_MODE=true，禁止生产库运行')
    from alembic import command
    from alembic.config import Config
    from fastapi.testclient import TestClient
    from PIL import Image
    from sqlalchemy import func, select
    from app import config, storage, ocr
    from app.db import engine, SessionLocal
    from app.models import Content, ContentVariant, Material, Metric, Interaction, Lead, Outbox, Topic
    from app.main import app
    from scripts.seed import seed, DEMO_PASSWORD
    cfg = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    with engine.begin() as conn:
        cfg.attributes['connection'] = conn
        command.upgrade(cfg, 'head')
    with SessionLocal() as db:
        seed(db, demo=True)
    report = {'mode': args.mode, 'status': 'running', 'demo_ai': True, 'ocr': 'deterministic-fixture',
              'push': 'HTTP-transport-fixture', 'steps': []}
    baseline = {}
    current = {'step': 'setup', 'request': None}
    out = Path(args.out)
    # 不覆盖已交付/既有报告；重复运行自动另存。
    if out.exists():
        from datetime import datetime
        out = out.with_name(out.stem + '-' + datetime.now().strftime('%Y%m%d-%H%M%S') + out.suffix)
    with ExitStack() as stack:
        if args.mode == 'isolated':
            objects = {}
            def put(data, filename, content_type='application/octet-stream'):
                ref = 's3://isolated/' + hashlib.sha256(data).hexdigest()
                objects[ref] = data
                return ref
            stack.enter_context(patch.object(storage, 'put', put))
        def recognize(data, kind):
            if kind == 'metrics':
                return '演示截图：播放1000 点赞32', {'views': 1000, 'likes': 32}, {'views': 0.75, 'likes': 0.96}
            comments = {'comments': [{'author_name': '演示工程商', 'body': '昆明学校LED项目询价，电话13800138000'}]}
            return '演示评论识别', comments, {'comments': 0.6}
        stack.enter_context(patch.object(ocr, 'recognize', recognize))
        import httpx
        calls = []
        def push_http(url, **kwargs):
            calls.append({'channel': 'wecom' if 'wecom' in url else 'crm',
                          'idempotency_key': kwargs.get('headers', {}).get('Idempotency-Key')})
            return httpx.Response(200, json={'errcode': 0, 'ok': True}, request=httpx.Request('POST', url))
        stack.enter_context(patch('app.notify.httpx.post', push_http))
        stack.enter_context(patch.object(config, 'WECOM_WEBHOOK', 'https://wecom.example.test/send'))
        stack.enter_context(patch.object(config, 'CRM_WEBHOOK', 'https://crm.example.test/leads'))
        with TestClient(app) as client:
            headers = {}
            def request(method, path, expected=200, **kwargs):
                current['request'] = {'method': method, 'path': path,
                    'json': {k: ('[REDACTED]' if 'password' in k else v) for k, v in kwargs.get('json', {}).items()}}
                response = client.request(method, '/api/v1' + path, headers=headers, **kwargs)
                if response.status_code != expected:
                    raise AssertionError(f'期望{expected}，实际{response.status_code}：{response.text[:2000]}')
                return response.json()
            def step(name):
                current['step'] = name
            def passed(data):
                report['steps'].append({'step': current['step'], 'status': 'passed', 'result': data})
            try:
                login = request('POST', '/auth/login', json={'username': 'admin', 'password': DEMO_PASSWORD})
                headers = {'Authorization': 'Bearer ' + login['token']}
                baseline = request('GET', '/dashboard/funnel')
                step('1 素材与双业务线选题')
                mats = request('GET', '/materials')
                topics = request('GET', '/topics')
                assert len(mats) >= 3 and {x['biz_line'] for x in topics} >= {'project', 'channel'}
                passed({'materials': len(mats), 'biz_lines': ['project', 'channel']})
                step('2 生成2×4平台版本')
                task = request('POST', '/generate/daily', expected=202, params={'scheduled': str(date.today())})
                task = request('GET', f'/tasks/{task["task_id"]}')
                assert task['status'] == 'succeeded', task
                ids = set(task['result']['content_ids'])
                contents = [c for c in request('GET', '/contents') if c['id'] in ids]
                variants = [v for c in contents for v in c['variants'] if v['is_current']]
                assert len(variants) == 8
                passed({'contents': len(contents), 'variants': len(variants), 'task_id': task['id']})
                step('3 驳回并保留历史/新版本')
                # 重跑时沿用已有驳回，不无限新增历史版本。
                history_old = next((v for c in contents for v in c['variants'] if v['confirm_status'] == 'rejected'), None)
                if history_old:
                    rejected_id = history_old['id']
                    fresh = next(v for v in variants if v['platform'] == history_old['platform'] and v['content_id'] == history_old['content_id'])
                else:
                    old = variants[0]
                    result = request('POST', f'/variants/{old["id"]}/reject', json={'reason': '需补充技术服务场景'})
                    rejected_id, fresh = old['id'], result['new_variant']
                assert fresh and fresh['revision'] >= 2
                history = request('GET', f'/variants/{rejected_id}/history')
                assert any(v['rejection_reason'] for v in history)
                passed({'old_id': rejected_id, 'new_id': fresh['id'], 'history_count': len(history)})
                step('4 通过7条并进入待办')
                contents = [c for c in request('GET', '/contents') if c['id'] in ids]
                current_variants = [v for c in contents for v in c['variants'] if v['is_current'] and v['id'] != fresh['id']]
                assert len(current_variants) == 7
                for v in current_variants:
                    if v['status'] != 'published' and v['confirm_status'] != 'confirmed':
                        request('POST', f'/variants/{v["id"]}/approve', json={})
                todo = request('GET', '/todo/today')['pending']
                target_ids = {v['id'] for v in current_variants}
                remaining = [v for v in todo if v['id'] in target_ids]
                already_published = [v for v in current_variants if v['status'] == 'published']
                assert len(remaining) + len(already_published) == 7
                passed({'target_approved': 7, 'pending_now': len(remaining), 'already_published_on_rerun': len(already_published)})
                step('5 有效链接回填，空链接不计数')
                v = current_variants[0]
                invalid = client.post(f'/api/v1/variants/{v["id"]}/publish', headers=headers, json={'published_url': ''})
                assert invalid.status_code == 422
                link = f'https://www.douyin.com/video/7300000000000{v["id"]:06d}'
                result = request('POST', f'/variants/{v["id"]}/publish', json={'published_url': v['published_url'] or link})
                assert result['status'] == 'published'
                passed({'variant_id': v['id'], 'published_url': result['published_url'], 'url_existence_verified': False})
                image = io.BytesIO(); Image.new('RGB', (200, 100), 'white').save(image, 'PNG')
                step('6 指标截图，确认前不入库')
                before = request('GET', '/dashboard/funnel')['views']
                task = request('POST', '/upload/screenshot', data={'kind': 'metrics', 'variant_id': str(v['id'])}, files={'f': ('metrics.png', image.getvalue(), 'image/png')})
                assert request('GET', '/dashboard/funnel')['views'] == before
                data = {'stat_date': str(date.today()), 'views': 1000, 'likes': 32, 'comments': 0,
                        'collects': 0, 'shares': 0, 'new_fans': 0, 'dm_inquiries': 0}
                request('POST', f'/ocr/tasks/{task["id"]}/confirm', json={'data': data, 'confirmed_fields': list(data)})
                passed({'task_id': task['id'], 'views': 1000, 'likes': 32, 'no_write_before_review': True})
                step('7 评论截图确认、互动、高意向线索与去重')
                task = request('POST', '/upload/screenshot', data={'kind': 'comments', 'variant_id': str(v['id'])}, files={'f': ('comments.png', image.getvalue(), 'image/png')})
                comments = {'comments': [{'author_name': '演示工程商', 'body': '昆明学校LED项目询价，电话13800138000'}]}
                result = request('POST', f'/ocr/tasks/{task["id"]}/confirm', json={'data': comments, 'confirmed_fields': ['comments']})
                lid = result['result']['lead_ids'][0]
                lead = request('POST', '/interactions', expected=201, json={'platform': 'gzh', 'body': '再次询价13800138000', 'author_name': '另一个昵称', 'source_key': f'e2e-repeat-{task["id"]}'})['lead']
                assert lead['id'] == lid and lead['intent'] == 'high' and lead['repeat']
                passed({'lead_id': lid, 'intent': 'high', 'dedup': 'merged', 'repeat': True})
                step('8 指派销售、队列可追踪/投递')
                assigned = request('PUT', f'/leads/{lid}', json={'assignee': 'sales01', 'follow_notes': '演示指派销售跟进'})
                assert assigned['assignee'] == 'sales01'
                request('POST', '/outbox/process')
                events = request('GET', '/outbox', params={'lead_id': lid})
                assert events and all(e['status'] == 'sent' for e in events)
                passed({'assignee': assigned['assignee'], 'events_sent': len(events), 'delivery': 'simulated-not-real-wecom', 'http_calls': len(calls)})
                step('9 看板与明细一致')
                dashboard = request('GET', '/dashboard/funnel')
                metrics = request('GET', '/metrics')
                with SessionLocal() as db:
                    assert dashboard['published'] == db.scalar(select(func.count(ContentVariant.id)).where(ContentVariant.status == 'published', ContentVariant.published_url != ''))
                    assert dashboard['views'] == (db.scalar(select(func.sum(Metric.views))) or 0)
                    assert dashboard['interactions'] == db.scalar(select(func.count(Interaction.id)))
                    assert dashboard['leads'] == db.scalar(select(func.count(Lead.id)))
                passed(dashboard)
                report['status'] = 'passed'
                report['limitations'] = ['AI为显式演示结果', 'OCR为可重复解析替身，真实引擎另行检查', '企微/CRM传输替身，不代表用户收到通知', 'URL仅格式验证，不验证文章存在', '未修改前端，等待双方联调']
            except Exception as exc:
                report['status'] = 'failed'
                report['failure'] = {'step': current['step'], 'request': current['request'], 'error': type(exc).__name__ + ': ' + str(exc)}
                with SessionLocal() as db:
                    report['database_state'] = {m.__tablename__: [
                        {c.name: getattr(x, c.name) for c in m.__table__.columns if c.name not in ('password_hash', 'access_token', 'appsecret')}
                        for x in db.scalars(select(m).order_by(m.id.desc()).limit(10)).all()]
                        for m in (Content, ContentVariant, Metric, Interaction, Lead, Outbox)}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(json.dumps({'status': report['status'], 'steps': len(report['steps']), 'report': str(out)}, ensure_ascii=False))
    if report['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()

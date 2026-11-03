from datetime import date
import httpx
import respx
from app import config
from .conftest import published, token_for
from .test_leads import interaction


@respx.mock
def test_outbox_failure_dead_and_manual_retry(client, headers, monkeypatch):
    monkeypatch.setattr(config, 'CRM_WEBHOOK', 'https://crm.example.test/leads')
    monkeypatch.setattr(config, 'WECOM_WEBHOOK', 'https://wecom.example.test/send')
    monkeypatch.setattr(config, 'OUTBOX_MAX_ATTEMPTS', 2)
    crm = respx.post(config.CRM_WEBHOOK).mock(return_value=httpx.Response(503))
    wecom = respx.post(config.WECOM_WEBHOOK).mock(return_value=httpx.Response(200, json={'errcode': 93000}))
    interaction(client, headers, '学校LED项目询价13800138000')
    assert client.post('/api/v1/outbox/process', headers=headers).status_code == 200
    events = client.get('/api/v1/outbox', headers=headers).json()
    assert len(events) == 2 and all(x['status'] == 'failed' and x['attempts'] == 1 for x in events)
    for event in events:
        result = client.post(f'/api/v1/outbox/{event["id"]}/retry', headers=headers)
        assert result.status_code == 200
        assert result.json()['status'] == 'dead'
    crm.mock(return_value=httpx.Response(200, json={'ok': True}))
    wecom.mock(return_value=httpx.Response(200, json={'errcode': 0}))
    for event in events:
        result = client.post(f'/api/v1/outbox/{event["id"]}/retry', headers=headers)
        assert result.json()['status'] == 'sent'
        assert result.json()['attempts'] == 3
        assert result.json()['last_error'] == ''
    assert crm.calls.last.request.headers['Idempotency-Key'].startswith('crm:lead:')
    sent_calls = crm.call_count
    for event in events:
        client.post(f'/api/v1/outbox/{event["id"]}/retry', headers=headers)
    assert crm.call_count == sent_calls


def test_unconfigured_notifications_are_traceable(client, headers):
    interaction(client, headers, '项目报价13800138000')
    result = client.post('/api/v1/outbox/process', headers=headers)
    assert result.json()['processed'] == 2
    assert all(x['last_error'] and x['status'] == 'failed' for x in client.get('/api/v1/outbox', headers=headers).json())


def test_dashboard_reconciles_and_metrics_upsert(client, headers):
    v = published(client, headers)
    data = {'variant_id': v['id'], 'stat_date': str(date.today()), 'views': 1000, 'likes': 32}
    for _ in range(2):
        assert client.post('/api/v1/metrics', json=data, headers=headers).status_code == 200
    interaction(client, headers, '项目报价13800138000')
    interaction(client, headers, '同一项目报价13800138000', platform='xhs')
    assert client.get('/api/v1/dashboard/funnel', headers=headers).json() == {
        'published': 1, 'views': 1000, 'interactions': 2, 'leads': 1, 'high_intent': 1}
    topics = client.get('/api/v1/dashboard/topics', headers=headers).json()
    assert sum(x['views'] for x in topics) == 1000
    assert sum(x['published'] for x in topics) == 1
    trend = client.get('/api/v1/dashboard/trend', headers=headers).json()
    assert len(trend) == 7 and trend[-1]['published'] == 1 and trend[-1]['views'] == 1000
    assert len(client.get('/api/v1/metrics', headers=headers).json()) == 1


def test_roles_password_rotation_and_legacy_routes(client, headers):
    assert client.get('/api/v1/contents').status_code == 401
    sales = token_for(client, 'sales01')
    for path in ['/materials', '/topics', '/contents', '/ai-jobs', '/outbox', '/metrics', '/dashboard/funnel', '/interactions']:
        assert client.get('/api/v1' + path, headers=sales).status_code == 403, path
    assert client.get('/api/v1/auth/me', headers=sales).status_code == 200
    op = token_for(client, 'yunying')
    assert client.post('/api/v1/rules', json={'rule_type': 'required', 'pattern': '新口径'}, headers=op).status_code == 403
    assert client.post('/api/v1/users', json={'username': 'extra', 'password': 'strong-password-123', 'role': 'admin'}, headers=op).status_code == 403
    assert client.get('/api/contents', headers=headers).headers['deprecation'] == 'true'
    from scripts.seed import DEMO_PASSWORD
    assert client.post('/api/v1/auth/password', json={'old_password': DEMO_PASSWORD, 'new_password': 'Changed-Password-2026!'}, headers=sales).status_code == 200
    assert client.get('/api/v1/auth/me', headers=sales).status_code == 401
    assert client.post('/api/v1/auth/login', json={'username': 'sales01', 'password': 'Changed-Password-2026!'}).status_code == 200


def test_soft_delete_and_openapi(client, headers):
    material = client.get('/api/v1/materials', headers=headers).json()[0]
    assert client.delete(f'/api/v1/materials/{material["id"]}', headers=headers).status_code == 200
    assert material['id'] not in [x['id'] for x in client.get('/api/v1/materials', headers=headers).json()]
    from app.main import app
    spec = app.openapi()
    assert spec['openapi'] == '3.1.0'
    assert all(path.startswith('/api/v1') for path in spec['paths'])
    assert '/api/v1/variants/{vid}/reject' in spec['paths']


@respx.mock
def test_browser_adapter_persists_fill_and_failure(client, headers, monkeypatch):
    from .conftest import generated
    monkeypatch.setattr(config, 'BROWSER_ENABLED', True)
    monkeypatch.setattr(config, 'BROWSER_ADAPTER_URL', 'https://browser.example.test')
    v = generated(client, headers)[0]
    client.post(f'/api/v1/variants/{v["id"]}/approve', json={}, headers=headers)
    route = respx.post(f'https://browser.example.test/{v["platform"]}/fill').mock(return_value=httpx.Response(200, json={'ok': True, 'published': False}))
    result = client.post(f'/api/v1/browser/{v["platform"]}/publish', json={'variant_id': v['id']}, headers=headers)
    assert result.status_code == 200 and result.json()['publish_status'] == 'filled'
    assert client.get('/api/v1/dashboard/funnel', headers=headers).json()['published'] == 0
    route.mock(return_value=httpx.Response(503))
    result = client.post(f'/api/v1/browser/{v["platform"]}/publish', json={'variant_id': v['id']}, headers=headers)
    assert result.json()['publish_status'] == 'failed'
    rows = client.get('/api/v1/contents', headers=headers).json()
    saved = next(x for c in rows for x in c['variants'] if x['id'] == v['id'])
    assert saved['publish_error']


def test_official_failure_persisted_without_false_publication(client, headers):
    from .conftest import generated
    v = generated(client, headers)[0]
    client.post(f'/api/v1/variants/{v["id"]}/approve', json={}, headers=headers)
    result = client.post(f'/api/v1/variants/{v["id"]}/publish/official', headers=headers)
    assert result.status_code == 200
    assert result.json()['publish_status'] == 'failed'
    assert result.json()['publish_error']
    assert client.get('/api/v1/dashboard/funnel', headers=headers).json()['published'] == 0

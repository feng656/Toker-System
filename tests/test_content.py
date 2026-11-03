from datetime import date
import pytest
from sqlalchemy import select
from app import config
from app.db import SessionLocal
from app.models import AIJob, ContentVariant, ReviewEvent
from .conftest import generated


def test_generation_is_idempotent_2_by_4(client, headers):
    variants = generated(client, headers)
    assert len(variants) == 8
    assert all(v['status'] == 'pending' for v in variants)
    ids = {v['id'] for v in variants}
    assert ids == {v['id'] for v in generated(client, headers)}
    jobs = client.get('/api/v1/ai-jobs', headers=headers).json()
    assert len(jobs) == 10
    assert all(j['status'] == 'succeeded' and j['demo'] for j in jobs)


def test_rejection_regenerates_with_history(client, headers):
    v = generated(client, headers)[0]
    assert client.post(f'/api/v1/variants/{v["id"]}/reject', json={'reason': ' '}, headers=headers).status_code == 422
    response = client.post(f'/api/v1/variants/{v["id"]}/reject', json={'reason': '补充本地技术服务能力'}, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['rejected']['rejection_reason'] == '补充本地技术服务能力'
    assert not result['rejected']['is_current']
    assert result['new_variant']['revision'] == 2
    assert result['new_variant']['parent_id'] == v['id']
    assert result['new_variant']['platform'] == v['platform']
    history = client.get(f'/api/v1/variants/{v["id"]}/history', headers=headers).json()
    assert [x['revision'] for x in history] == [1, 2]
    assert client.post(f'/api/v1/variants/{v["id"]}/approve', json={}, headers=headers).status_code == 409
    retry = client.post(f'/api/v1/variants/{v["id"]}/regenerate', headers=headers).json()
    assert retry['new_variant']['id'] == result['new_variant']['id']
    with SessionLocal() as db:
        assert len(db.scalars(select(ReviewEvent)).all()) == 1


def test_only_approved_current_variants_are_todo(client, headers):
    variants = generated(client, headers)
    old = variants[0]
    rejected = client.post(f'/api/v1/variants/{old["id"]}/reject', json={'reason': '更具体'}, headers=headers).json()
    assert client.get('/api/v1/todo/today', headers=headers).json()['pending'] == []
    for v in variants[1:]:
        assert client.post(f'/api/v1/variants/{v["id"]}/approve', json={}, headers=headers).status_code == 200
    todo = client.get('/api/v1/todo/today', headers=headers).json()['pending']
    assert len(todo) == 7
    assert old['id'] not in {v['id'] for v in todo}
    assert rejected['new_variant']['id'] not in {v['id'] for v in todo}


@pytest.mark.parametrize('url', ['', '  ', 'gzh:media_id=123', 'douyin:item=123',
    'javascript:alert(1)', 'http://localhost/a', 'http://127.0.0.1/a',
    'https://example.com/a', 'https://www.douyin.com', 'https://user:pass@www.douyin.com/a'])
def test_invalid_publish_links_do_not_count(client, headers, url):
    v = generated(client, headers)[0]
    assert client.post(f'/api/v1/variants/{v["id"]}/approve', json={}, headers=headers).status_code == 200
    result = client.post(f'/api/v1/variants/{v["id"]}/publish', json={'published_url': url}, headers=headers)
    assert result.status_code == 422, result.text
    assert client.get('/api/v1/dashboard/funnel', headers=headers).json()['published'] == 0


def test_publication_is_real_link_gated_and_idempotent(client, headers):
    v = generated(client, headers)[0]
    payload = {'published_url': 'https://www.douyin.com/video/7300000000000000001'}
    assert client.post(f'/api/v1/variants/{v["id"]}/publish', json=payload, headers=headers).status_code == 409
    client.post(f'/api/v1/variants/{v["id"]}/approve', json={}, headers=headers)
    for _ in range(2):
        response = client.post(f'/api/v1/variants/{v["id"]}/publish', json=payload, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'published'
    assert client.get('/api/v1/dashboard/funnel', headers=headers).json()['published'] == 1
    assert len(client.get('/api/v1/todo/today', headers=headers).json()['pending']) == 0
    assert client.put(f'/api/v1/variants/{v["id"]}', json={'body': '改已发正文 私信询价'}, headers=headers).status_code == 409


@pytest.mark.parametrize('text,hit', [('内容无行动口径', 'required:'), ('成本价 私信询价', 'forbidden:'), ('全国第一 私信询价', 'ad_law:')])
def test_compliance_blocks_single_and_bulk_approval(client, headers, text, hit):
    v = generated(client, headers)[0]
    result = client.put(f'/api/v1/variants/{v["id"]}', json={'body': text, 'cover_text': '', 'hashtags': ''}, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'blocked'
    assert hit in result.json()['compliance_hits']
    assert client.post(f'/api/v1/variants/{v["id"]}/approve', json={}, headers=headers).status_code == 409
    assert client.post(f'/api/v1/contents/{v["content_id"]}/review', json={'action': 'approve'}, headers=headers).status_code == 409


def test_edit_invalidates_approval_and_optimistic_version(client, headers):
    v = generated(client, headers)[0]
    approved = client.post(f'/api/v1/variants/{v["id"]}/approve', json={}, headers=headers).json()
    assert client.put(f'/api/v1/variants/{v["id"]}', json={'body': '新文案 私信询价', 'expected_version': v['version']}, headers=headers).status_code == 409
    edited = client.put(f'/api/v1/variants/{v["id"]}', json={'body': '新文案 私信询价', 'expected_version': approved['version']}, headers=headers)
    assert edited.status_code == 200
    assert edited.json()['status'] == 'draft'
    assert edited.json()['confirm_status'] == 'none'
    assert client.post(f'/api/v1/variants/{v["id"]}/approve', json={}, headers=headers).status_code == 409
    assert client.post(f'/api/v1/variants/{v["id"]}/quality', json={}, headers=headers).json()['status'] == 'pending'


def test_ai_failure_has_audit_and_retry(client, headers, monkeypatch):
    monkeypatch.setattr(config, 'DEMO_MODE', False)
    response = client.post('/api/v1/generate/daily', params={'scheduled': str(date.today())}, headers=headers)
    task_id = response.json()['task_id']
    task = client.get(f'/api/v1/tasks/{task_id}', headers=headers).json()
    assert task['status'] == 'failed'
    assert client.get('/api/v1/contents', headers=headers).json() == []
    jobs = client.get('/api/v1/ai-jobs', headers=headers).json()
    assert any(j['status'] == 'failed' and j['kind'] == 'generate' for j in jobs)
    monkeypatch.setattr(config, 'DEMO_MODE', True)
    assert client.post(f'/api/v1/tasks/{task_id}/retry', headers=headers).status_code == 202
    assert client.get(f'/api/v1/tasks/{task_id}', headers=headers).json()['status'] == 'succeeded'


def test_rejection_ai_failure_keeps_reason_and_is_retryable(client, headers, monkeypatch):
    v = generated(client, headers)[0]
    monkeypatch.setattr(config, 'DEMO_MODE', False)
    response = client.post(f'/api/v1/variants/{v["id"]}/reject', json={'reason': '更具体的交付场景'}, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['new_variant'] is None
    assert response.json()['rejected']['rejection_reason'] == '更具体的交付场景'
    monkeypatch.setattr(config, 'DEMO_MODE', True)
    retry = client.post(f'/api/v1/variants/{v["id"]}/regenerate', headers=headers)
    assert retry.status_code == 200 and retry.json()['new_variant']['revision'] == 2

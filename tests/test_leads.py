from datetime import timedelta
from sqlalchemy import select
from app.db import SessionLocal, utcnow
from app.models import Lead
from app.classifier import contact_keys, similarity
from .conftest import token_for


def interaction(client, headers, body, **kwargs):
    payload = {'platform': 'douyin', 'body': body, 'author_name': '工程商老王', **kwargs}
    response = client.post('/api/v1/interactions', json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_contact_normalization():
    assert contact_keys('电话 +86 138-0013-8000') == ['phone:13800138000']
    assert contact_keys('微信：Berry_2026') == ['wx:berry_2026']
    assert contact_keys('Contact@EXAMPLE.COM') == ['email:contact@example.com']


def test_contact_priority_cross_platform_dedup(client, headers):
    first = interaction(client, headers, '学校LED项目询价 13800138000')
    second = interaction(client, headers, '另一平台咨询报价 13800138000', platform='gzh', author_name='不同昵称')
    assert first['lead']['id'] == second['lead']['id']
    assert second['lead']['repeat'] and second['lead']['repeat_count'] == 1
    detail = client.get(f'/api/v1/leads/{first["lead"]["id"]}', headers=headers).json()
    assert len(detail['sources']) == 2
    assert detail['sources'][1]['match_reason'] == 'contact'


def test_30_day_boundary_creates_new_lead(client, headers):
    first = interaction(client, headers, '项目报价 13800138000')
    with SessionLocal() as db:
        lead = db.get(Lead, first['lead']['id'])
        lead.last_seen_at = lead.created_at = utcnow() - timedelta(days=31)
        db.commit()
    second = interaction(client, headers, '项目报价 13800138000')
    assert first['lead']['id'] != second['lead']['id']


def test_author_fallback_and_contact_conflict(client, headers):
    first = interaction(client, headers, 'LED型号咨询', author_id='same-person')
    second = interaction(client, headers, '项目要合作', author_id='same-person')
    assert first['lead']['id'] == second['lead']['id']
    third = interaction(client, headers, '项目报价13800138000', author_id='other-person')
    fourth = interaction(client, headers, '项目报价13900139000', author_id='other-person')
    assert third['lead']['id'] != fourth['lead']['id']


def test_need_similarity_fallback(client, headers):
    text = '我们在昆明有学校报告厅LED屏项目需要技术团队配合交付'
    first = interaction(client, headers, text, author_name='')
    second = interaction(client, headers, text + '。', author_name='')
    assert first['lead']['id'] == second['lead']['id']
    assert similarity('咨询', '咨询') == 0


def test_source_idempotency_and_classification_retry(client, headers):
    first = interaction(client, headers, '项目报价13800138000', source_key='demo-comment-1')
    second = interaction(client, headers, '项目报价13800138000', source_key='demo-comment-1')
    assert first['interaction_id'] == second['interaction_id']
    response = client.post(f'/api/v1/interactions/{first["interaction_id"]}/classify', headers=headers)
    assert response.status_code == 200
    assert response.json()['lead']['repeat_count'] == 0
    assert len(client.get('/api/v1/leads', headers=headers).json()) == 1


def test_assignment_sales_visibility_and_followup(client, headers):
    first = interaction(client, headers, '项目报价13800138000')['lead']
    a, b = token_for(client, 'sales01'), token_for(client, 'sales02')
    assert client.get('/api/v1/leads', headers=a).json() == []
    assert client.get(f'/api/v1/leads/{first["id"]}', headers=a).status_code == 404
    result = client.put(f'/api/v1/leads/{first["id"]}', json={'assignee': 'sales01', 'expected_version': first['version']}, headers=headers)
    assert result.status_code == 200, result.text
    assert len(client.get('/api/v1/leads', headers=a).json()) == 1
    assert client.get('/api/v1/leads', headers=b).json() == []
    assert client.put(f'/api/v1/leads/{first["id"]}', json={'assignee': 'sales02'}, headers=a).status_code == 403
    assert client.put(f'/api/v1/leads/{first["id"]}', json={'status': 'contacted', 'follow_notes': '已电话沟通需求'}, headers=a).status_code == 200
    detail = client.get(f'/api/v1/leads/{first["id"]}', headers=a).json()
    assert len(detail['followups']) == 2 and detail['status'] == 'contacted'
    assert client.put(f'/api/v1/leads/{first["id"]}', json={'status': 'wechat_added'}, headers=a).status_code == 422
    assert client.put(f'/api/v1/leads/{first["id"]}', json={'assignee': 'admin'}, headers=headers).status_code == 422

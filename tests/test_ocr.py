from datetime import date
import pytest
from app import ocr, config
from .conftest import published, generated


def upload(client, headers, image, vid, kind='metrics'):
    response = client.post('/api/v1/upload/screenshot', data={'kind': kind, 'variant_id': str(vid)},
                           files={'f': ('shot.png', image, 'image/png')}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_ocr_no_business_write_before_confirmation(client, headers, image_bytes, fake_storage, monkeypatch):
    v = published(client, headers)
    monkeypatch.setattr(ocr, 'recognize', lambda *_: ('播放100 点赞5', {'views': 100, 'likes': 5}, {'views': 0.8, 'likes': 0.95}))
    task = upload(client, headers, image_bytes, v['id'])
    assert task['status'] == 'pending_review'
    assert 'views' in task['low_confidence_fields']
    assert 'comments' in task['low_confidence_fields']
    assert client.get('/api/v1/metrics', headers=headers).json() == []
    data = {'stat_date': str(date.today()), 'views': 100, 'likes': 5, 'comments': 0, 'collects': 0, 'shares': 0, 'new_fans': 0, 'dm_inquiries': 0}
    assert client.post(f'/api/v1/ocr/tasks/{task["id"]}/confirm', json={'data': data}, headers=headers).status_code == 422
    payload = {'data': data, 'confirmed_fields': task['low_confidence_fields']}
    confirmed = client.post(f'/api/v1/ocr/tasks/{task["id"]}/confirm', json=payload, headers=headers)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()['status'] == 'confirmed'
    assert client.post(f'/api/v1/ocr/tasks/{task["id"]}/confirm', json=payload, headers=headers).status_code == 200
    metrics = client.get('/api/v1/metrics', headers=headers).json()
    assert len(metrics) == 1 and metrics[0]['views'] == 100 and metrics[0]['likes'] == 5
    assert metrics[0]['source'] == 'ocr'
    assert upload(client, headers, image_bytes, v['id'])['id'] == task['id']
    assert client.post(f'/api/v1/ocr/tasks/{task["id"]}/retry', headers=headers).status_code == 409


def test_missing_low_confidence_value_cannot_default_zero(client, headers, image_bytes, fake_storage, monkeypatch):
    v = published(client, headers)
    monkeypatch.setattr(ocr, 'recognize', lambda *_: ('', {}, {}))
    task = upload(client, headers, image_bytes, v['id'])
    response = client.post(f'/api/v1/ocr/tasks/{task["id"]}/confirm',
        json={'data': {'stat_date': str(date.today())}, 'confirmed_fields': task['low_confidence_fields']}, headers=headers)
    assert response.status_code == 422
    assert client.get('/api/v1/metrics', headers=headers).json() == []


def test_comment_ocr_creates_interaction_and_lead_after_confirmation(client, headers, image_bytes, fake_storage, monkeypatch):
    v = published(client, headers)
    comments = {'comments': [{'author_name': '工程商王先生', 'body': '我们有学校LED项目要报价，电话13800138000'}]}
    monkeypatch.setattr(ocr, 'recognize', lambda *_: ('识别原文', comments, {'comments': 0.4}))
    task = upload(client, headers, image_bytes, v['id'], 'comments')
    assert client.get('/api/v1/interactions', headers=headers).json() == []
    response = client.post(f'/api/v1/ocr/tasks/{task["id"]}/confirm',
                           json={'data': comments, 'confirmed_fields': ['comments']}, headers=headers)
    assert response.status_code == 200, response.text
    assert len(response.json()['result']['interaction_ids']) == 1
    leads = client.get('/api/v1/leads', headers=headers).json()
    assert len(leads) == 1 and leads[0]['intent'] == 'high'
    assert 'phone:13800138000' in leads[0]['contact_keys']
    assert len(client.get('/api/v1/outbox', headers=headers).json()) == 2


def test_ocr_failure_manual_review_and_retry(client, headers, image_bytes, fake_storage, monkeypatch):
    v = published(client, headers)
    def fail(*_):
        raise TimeoutError('not reachable')
    monkeypatch.setattr(ocr, 'recognize', fail)
    task = upload(client, headers, image_bytes, v['id'])
    assert task['status'] == 'pending_review' and task['error']
    monkeypatch.setattr(ocr, 'recognize', lambda *_: ('播放12', {'views': 12}, {'views': 0.9}))
    result = client.post(f'/api/v1/ocr/tasks/{task["id"]}/retry', headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()['attempts'] == 2 and result.json()['error'] == ''
    assert client.get('/api/v1/metrics', headers=headers).json() == []


def test_upload_errors_and_unpublished_metrics(client, headers, image_bytes, fake_storage):
    v = generated(client, headers)[0]
    invalid = client.post('/api/v1/upload/screenshot', data={'kind': 'metrics', 'variant_id': str(v['id'])},
                          files={'f': ('shot.png', b'not an image', 'image/png')}, headers=headers)
    assert invalid.status_code == 422
    assert client.post('/api/v1/metrics', json={'variant_id': v['id'], 'stat_date': str(date.today()), 'views': 5}, headers=headers).status_code == 409
    assert client.post('/api/v1/metrics', json={'variant_id': v['id'], 'stat_date': str(date.today()), 'views': -1}, headers=headers).status_code == 422


def test_parse_metrics_units():
    fields, confidence = ocr.parse_text('播放 1.2万\n点赞 100\n评论 5', 'metrics', 0.9)
    assert fields['views'] == 12000 and fields['likes'] == 100 and fields['comments'] == 5
    assert confidence['shares'] == 0

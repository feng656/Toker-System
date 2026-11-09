"""默认内存隔离测试；TEST_DATABASE_URL可切换专用Postgres测试schema。"""
import os
os.environ.setdefault('APP_ENV', 'test')
os.environ.setdefault('DATABASE_URL', os.getenv('TEST_DATABASE_URL', 'sqlite:///:memory:'))
os.environ.setdefault('JWT_SECRET', 'test-only-key-not-for-production-0123456789')
os.environ.setdefault('DEMO_MODE', 'true')
os.environ.setdefault('SCHEDULER_ENABLED', 'false')

from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from app import config
from app.db import Base, engine, SessionLocal
from app.main import app
from scripts.seed import seed, DEMO_PASSWORD


@pytest.fixture(autouse=True)
def db_reset(monkeypatch):
    monkeypatch.setattr(config, 'DEMO_MODE', True)
    monkeypatch.setattr(config, 'LLM_PROVIDERS', [])
    monkeypatch.setattr(config, 'CRM_WEBHOOK', '')
    monkeypatch.setattr(config, 'WECOM_WEBHOOK', '')
    monkeypatch.setattr(config, 'OFFICIAL_PUBLISH_ENABLED', False)
    monkeypatch.setattr(config, 'AUTO_REGISTER_MODE', 'off')
    monkeypatch.setattr(config, 'LOGIN_IP_LIMIT', 1000)
    monkeypatch.setattr(config, 'LOGIN_ACCOUNT_LIMIT', 1000)
    if engine.dialect.name == 'postgresql' and os.getenv('ALLOW_TEST_DATABASE_RESET') != 'yes':
        raise RuntimeError('真库测试须设置ALLOW_TEST_DATABASE_RESET=yes并使用独立测试schema')
    cfg = Config(str(Path(__file__).resolve().parents[1] / 'alembic.ini'))
    with engine.connect() as conn:
        if conn.dialect.name == 'sqlite':
            # SQLite batch重建被引用表时必须临时关闭FK；测试重置结束立即恢复并检查。
            conn.exec_driver_sql('PRAGMA foreign_keys=OFF');conn.commit()
        with conn.begin():
            cfg.attributes['connection'] = conn
            command.downgrade(cfg, 'base') if conn.dialect.has_table(conn, 'alembic_version') else None
            command.upgrade(cfg, 'head')
        if conn.dialect.name == 'sqlite':
            conn.exec_driver_sql('PRAGMA foreign_keys=ON')
            assert not conn.exec_driver_sql('PRAGMA foreign_key_check').all()
            conn.commit()
    with SessionLocal() as db:
        seed(db, demo=True)
    yield


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def headers(client):
    response = client.post('/api/v1/auth/login', json={'username': 'admin', 'password': DEMO_PASSWORD})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['token']}


def token_for(client, name):
    response = client.post('/api/v1/auth/login', json={'username': name, 'password': DEMO_PASSWORD})
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['token']}


def generated(client, headers):
    from datetime import date
    result = client.post('/api/v1/generate/daily', params={'scheduled': str(date.today())}, headers=headers)
    assert result.status_code == 202, result.text
    task = client.get('/api/v1/tasks/' + str(result.json()['task_id']), headers=headers).json()
    assert task['status'] == 'succeeded', task
    rows = client.get('/api/v1/contents', headers=headers).json()
    assert len(rows) == 2
    return [v for c in rows for v in c['variants'] if v['is_current']]


def published(client, headers):
    v = generated(client, headers)[0]
    assert client.post(f'/api/v1/variants/{v["id"]}/approve', json={}, headers=headers).status_code == 200
    result = client.post(f'/api/v1/variants/{v["id"]}/publish', json={'published_url': 'https://www.douyin.com/video/7300000000000000001'}, headers=headers)
    assert result.status_code == 200, result.text
    return result.json()


@pytest.fixture
def image_bytes():
    import io
    from PIL import Image
    output = io.BytesIO()
    Image.new('RGB', (120, 60), 'white').save(output, 'PNG')
    return output.getvalue()


@pytest.fixture
def fake_storage(monkeypatch):
    from app import storage
    objects = {}
    def put(data, filename, content_type='application/octet-stream'):
        ref = 's3://test/' + str(len(objects) + 1)
        objects[ref] = data
        return ref
    monkeypatch.setattr(storage, 'put', put)
    monkeypatch.setattr(storage, 'get', lambda ref: objects[ref])
    return objects

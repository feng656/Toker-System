import base64
from datetime import datetime, timedelta, timezone
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, func
from app import config, workspace
from app.db import SessionLocal, utcnow
from app.models import Platform, WorkspaceAccount, AutomationEvent
from .conftest import generated, token_for


def catalog(client, headers):
    r=client.get('/api/v1/workspace/platforms',headers=headers)
    assert r.status_code==200,r.text
    return r.json()


def account(client,headers,**extra):
    pf=next(p for p in catalog(client,headers) if p['code']=='douyin')
    r=client.post('/api/v1/workspace/accounts',headers=headers,json={'platform_id':pf['id'],'label':'测试主号','login_hint':'brand-account','request_key':'test-account-key-123456',**extra})
    assert r.status_code==201,r.text
    return r.json()


def response_qr(image_bytes,attempt='attempt-1'):
    return {'ok':True,'status':'awaiting_scan','attempt_id':attempt,
        'qr_png_base64':base64.b64encode(image_bytes).decode(),
        'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=3)).isoformat()}


def test_catalog_mainstream_complete_no_generation_expansion(client,headers):
    rows=catalog(client,headers)
    assert {p['code'] for p in rows}>={'douyin','xhs','shipinhao','gzh','kuaishou','bilibili','weibo','zhihu','toutiao','baijiahao','taobao','jd','pinduoduo','xianyu','alibaba1688'}
    assert 'moments' not in {p['code'] for p in rows}
    assert next(p['name'] for p in rows if p['code']=='xhs')=='小红书'
    assert all(p['qr_status']=='unconfigured' for p in rows if p['enabled'])
    assert len(generated(client,headers))==8
    assert all(not p['generation_enabled'] for p in rows if p['code'] in ('weibo','jd','taobao'))


def test_custom_platform_saved_idempotent_selectable_and_no_secret(client,headers):
    body={'name':'企业社区','category':'text','login_url':'https://community.company.com/login','request_key':'custom-platform-key-1234'}
    a=client.post('/api/v1/workspace/platforms',headers=headers,json=body)
    assert a.status_code==201,a.text
    b=client.post('/api/v1/workspace/platforms',headers=headers,json=body)
    assert b.json()['id']==a.json()['id']
    assert a.json()['generation_enabled'] is False
    assert a.json()['builtin'] is False
    assert a.json()['id'] in [p['id'] for p in catalog(client,headers)]
    # 刷新再选平台创建账号，独立session会看到同一持久化平台。
    account(client,headers,platform_id=a.json()['id'])
    conflict=client.post('/api/v1/workspace/platforms',headers=headers,json={**body,'name':'其他社区'})
    assert conflict.status_code==409
    duplicate=client.post('/api/v1/workspace/platforms',headers=headers,json={**body,'request_key':'different-request-key'})
    assert duplicate.status_code==409
    assert 'session_ciphertext' not in a.text


@pytest.mark.parametrize('url',['javascript:alert(1)','http://company.com','https://user:pass@company.com','https://127.0.0.1/login','https://192.168.1.1/login','https://company.com/?token=secret','https://127.1/login','https://console.local./','https://public.com\\@127.0.0.1/'])
def test_custom_login_url_rejects_unsafe(client,headers,url):
    r=client.post('/api/v1/workspace/platforms',headers=headers,json={'name':'测试','login_url':url,'request_key':'custom-platform-key-unsafe'})
    assert r.status_code==422


def test_custom_permissions_and_duplicate_account_retry(client,headers):
    op=token_for(client,'yunying')
    sales=token_for(client,'sales01')
    assert client.post('/api/v1/workspace/platforms',headers=op,json={'name':'x','request_key':'request-key-123456789'}).status_code==403
    assert client.get('/api/v1/workspace/platforms',headers=sales).status_code==403
    first=account(client,headers);again=account(client,headers)
    assert first['id']==again['id'] and 'request_key' not in first
    pf=first['platform_id']
    assert client.post('/api/v1/workspace/accounts',headers=headers,json={'platform_id':pf,'label':'different','request_key':'test-account-key-123456'}).status_code==409


def test_saved_account_then_qr_then_active_refresh_connects(client,headers,monkeypatch,image_bytes,fake_storage):
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.setattr('app.storage.signed_url',lambda _: 'https://storage.example.test/qr.png')
    a=account(client,headers);seen=[];qr=response_qr(image_bytes)
    def adapter(action,payload,request_key=None):
        seen.append((action,payload))
        if action=='accounts/login':return qr
        return {'ok':True,'status':'connected','session':{'handle':'private-session'},'nickname':'实际扫码账号','expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
    monkeypatch.setattr(workspace,'request',adapter)
    r=client.post(f'/api/v1/workspace/accounts/{a["id"]}/login',headers=headers,json={'login_mode':'qr'})
    assert r.status_code==200,r.text
    assert seen[0][1]['username']=='brand-account' and seen[0][1]['password']==''
    s=client.get(f'/api/v1/workspace/accounts/{a["id"]}/session',headers=headers).json()
    assert s['qr_available'] and s['qr_url']
    # GET本地状态不触发平台查询，POST refresh才推动授权状态。
    assert len(seen)==1
    client.post(f'/api/v1/workspace/accounts/{a["id"]}/login',headers=headers,json={})
    assert len(seen)==1  # 未到期扫码请求重试复用
    r=client.post(f'/api/v1/workspace/accounts/{a["id"]}/refresh',headers=headers)
    assert r.json()['status']=='connected' and r.json()['nickname']=='实际扫码账号'
    assert not r.json()['qr_available'] and 'private-session' not in r.text
    assert seen[-1][1]['platform']=='douyin'


def test_refresh_waiting_no_new_image_and_no_audit_spam(client,headers,monkeypatch,image_bytes,fake_storage):
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    a=account(client,headers);qr=response_qr(image_bytes)
    monkeypatch.setattr(workspace,'request',lambda *args,**kw:qr)
    assert client.post(f'/api/v1/workspace/accounts/{a["id"]}/login',headers=headers,json={}).status_code==200
    waiting={k:v for k,v in qr.items() if k!='qr_png_base64'}
    monkeypatch.setattr(workspace,'request',lambda *args,**kw:waiting)
    for _ in range(3):assert client.post(f'/api/v1/workspace/accounts/{a["id"]}/refresh',headers=headers).json()['status']=='awaiting_scan'
    assert len(fake_storage)==1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AutomationEvent).where(AutomationEvent.resource=='account'))==1


def test_expired_qr_has_no_url_and_refresh_stays_local(client,headers,monkeypatch,image_bytes,fake_storage):
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    a=account(client,headers)
    monkeypatch.setattr(workspace,'request',lambda *args,**kw:response_qr(image_bytes))
    assert client.post(f'/api/v1/workspace/accounts/{a["id"]}/login',headers=headers,json={}).status_code==200
    with SessionLocal() as db:
        row=db.get(WorkspaceAccount,a['id']);row.qr_expires_at=utcnow()-timedelta(seconds=1);db.commit()
    s=client.get(f'/api/v1/workspace/accounts/{a["id"]}/session',headers=headers).json()
    assert s['status']=='expired' and not s['qr_available'] and 'qr_url' not in s
    monkeypatch.setattr(workspace,'request',lambda *_:pytest.fail('过期不应再轮询旧远端会话'))
    assert client.post(f'/api/v1/workspace/accounts/{a["id"]}/refresh',headers=headers).json()['status']=='expired'


def test_missing_adapter_saves_account_without_fake_qr(client,headers,monkeypatch):
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.setattr(config,'BROWSER_ENABLED',False)
    a=account(client,headers)
    r=client.post(f'/api/v1/workspace/accounts/{a["id"]}/login',headers=headers,json={})
    assert r.status_code==503
    s=client.get(f'/api/v1/workspace/accounts/{a["id"]}/session',headers=headers).json()
    assert s['status']=='disconnected' and not s['qr_available'] and 'qr_url' not in s
    assert len(client.get('/api/v1/workspace/accounts',headers=headers).json())==1


def test_platform_disabled_or_not_supported_cannot_login(client,headers,monkeypatch):
    a=account(client,headers)
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.setattr(config,'BROWSER_ENABLED',True);monkeypatch.setattr(config,'BROWSER_ADAPTER_URL','https://trusted.example.test')
    monkeypatch.setattr(config,'BROWSER_ADAPTER_TOKEN','test-only');monkeypatch.setattr(config,'BROWSER_LOGIN_PLATFORMS',['gzh'])
    assert next(p for p in catalog(client,headers) if p['code']=='douyin')['qr_status']=='unsupported'
    assert client.post(f'/api/v1/workspace/accounts/{a["id"]}/login',headers=headers,json={}).status_code==409
    with SessionLocal() as db:
        p=db.get(Platform,a['platform_id']);p.enabled=False;db.commit()
    assert client.post(f'/api/v1/workspace/accounts/{a["id"]}/login',headers=headers,json={}).status_code==409


def test_legacy_platform_update_preserves_login_only_scope(client,headers):
    p=next(p for p in catalog(client,headers) if p['code']=='jd')
    r=client.put(f'/api/v1/platforms/{p["id"]}',headers=headers,json={'code':'jd','name':'京东','category':'commerce','enabled':True})
    assert r.status_code==200 and not r.json()['generation_enabled']
    assert r.json()['login_url']==p['login_url']


def test_qr_storage_failure_is_explicit_and_account_remains_saved(client,headers,monkeypatch,image_bytes):
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    a=account(client,headers)
    monkeypatch.setattr(workspace,'request',lambda *args,**kw:response_qr(image_bytes))
    def unavailable(*args):raise RuntimeError('test-storage-unavailable')
    monkeypatch.setattr('app.storage.put',unavailable)
    r=client.post(f'/api/v1/workspace/accounts/{a["id"]}/login',headers=headers,json={})
    assert r.status_code==503 and '二维码存储不可用' in r.text
    s=client.get(f'/api/v1/workspace/accounts/{a["id"]}/session',headers=headers).json()
    assert not s['qr_available'] and s['status']=='disconnected'


def test_deleted_platform_login_is_blocked(client,headers,monkeypatch):
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    a=account(client,headers)
    with SessionLocal() as db:
        p=db.get(Platform,a['platform_id']);p.deleted_at=utcnow();db.commit()
    monkeypatch.setattr(workspace,'request',lambda *_:pytest.fail('deleted platform must not call adapter'))
    assert client.post(f'/api/v1/workspace/accounts/{a["id"]}/login',headers=headers,json={}).status_code==409


def test_qr_capability_requires_trusted_endpoint_and_valid_cipher(client,headers,monkeypatch):
    monkeypatch.setattr(config,'BROWSER_ENABLED',True)
    monkeypatch.setattr(config,'BROWSER_ADAPTER_URL','https://trusted.example.test')
    monkeypatch.setattr(config,'BROWSER_ADAPTER_TOKEN','test-only')
    monkeypatch.setattr(config,'BROWSER_LOGIN_PLATFORMS',['douyin'])
    monkeypatch.setattr(config,'ADAPTER_ALLOWED_HOSTS',['trusted.example.test'])
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY','')
    get=lambda:next(p for p in catalog(client,headers) if p['code']=='douyin')
    assert get()['qr_status']=='unconfigured'
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    assert get()['qr_status']=='configured'
    monkeypatch.setattr(config,'ADAPTER_ALLOWED_HOSTS',[])
    assert get()['qr_status']=='unconfigured'

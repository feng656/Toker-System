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


def test_explicit_fresh_login_replaces_valid_qr(client,headers,monkeypatch,image_bytes,fake_storage):
    import io
    from PIL import Image
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    a=account(client,headers);seen=[]
    first=response_qr(image_bytes,'attempt-1')
    out=io.BytesIO();Image.new('RGB',(120,60),'black').save(out,'PNG')
    second={'ok':True,'status':'awaiting_scan','attempt_id':'attempt-2',
            'qr_png_base64':base64.b64encode(out.getvalue()).decode(),
            'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=3)).isoformat()}
    def adapter(action,payload,request_key=None):
        seen.append(action);return first if len(seen)==1 else second
    monkeypatch.setattr(workspace,'request',adapter)
    assert client.post(f'/api/v1/workspace/accounts/{a["id"]}/login',headers=headers,json={'login_mode':'qr'}).status_code==200
    assert len(seen)==1
    # 默认重试仍复用未过期二维码，避免网络重试重复创建远端会话。
    assert client.post(f'/api/v1/workspace/accounts/{a["id"]}/login',headers=headers,json={'login_mode':'qr'}).status_code==200
    assert len(seen)==1
    # 用户主动刷新必须拿到完整寿命的新码。
    assert client.post(f'/api/v1/workspace/accounts/{a["id"]}/login',headers=headers,json={'login_mode':'qr','fresh':True}).status_code==200
    assert len(seen)==2 and len(fake_storage)==2
    with SessionLocal() as db:
        assert db.get(WorkspaceAccount,a['id']).login_attempt_id=='attempt-2'


def test_refresh_rotated_qr_replaces_stored_image(client,headers,monkeypatch,image_bytes,fake_storage):
    import io
    from PIL import Image
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    a=account(client,headers);qr=response_qr(image_bytes)
    monkeypatch.setattr(workspace,'request',lambda *args,**kw:qr)
    assert client.post(f'/api/v1/workspace/accounts/{a["id"]}/login',headers=headers,json={}).status_code==200
    out=io.BytesIO();Image.new('RGB',(120,60),'black').save(out,'PNG')
    # 平台在同一次 attempt 内轮换二维码：expires_at 不变，但图片内容已更新。
    rotated={**qr,'qr_png_base64':base64.b64encode(out.getvalue()).decode()}
    monkeypatch.setattr(workspace,'request',lambda *args,**kw:rotated)
    r=client.post(f'/api/v1/workspace/accounts/{a["id"]}/refresh',headers=headers)
    assert r.json()['status']=='awaiting_scan'
    assert len(fake_storage)==2
    with SessionLocal() as db:
        assert db.get(WorkspaceAccount,a['id']).qr_object_ref=='s3://test/2'


def test_expired_local_qr_still_asks_adapter_for_rotation(client,headers,monkeypatch,image_bytes,fake_storage):
    import io
    from PIL import Image
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    a=account(client,headers)
    monkeypatch.setattr(workspace,'request',lambda *args,**kw:response_qr(image_bytes))
    assert client.post(f'/api/v1/workspace/accounts/{a["id"]}/login',headers=headers,json={}).status_code==200
    with SessionLocal() as db:
        row=db.get(WorkspaceAccount,a['id']);row.qr_expires_at=utcnow()-timedelta(seconds=1);db.commit()
    s=client.get(f'/api/v1/workspace/accounts/{a["id"]}/session',headers=headers).json()
    assert s['status']=='expired' and not s['qr_available'] and 'qr_url' not in s
    # 本地倒计时到期不等于平台会话失效：必须继续问适配器，若平台已轮换出新码
    # 就恢复 awaiting_scan 并更新图片，而不是直接判死、把刚确认的登录丢掉。
    out=io.BytesIO();Image.new('RGB',(160,160),'black').save(out,'PNG')
    rotated={'ok':True,'status':'awaiting_scan','attempt_id':'attempt-1',
        'qr_png_base64':base64.b64encode(out.getvalue()).decode(),
        'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=3)).isoformat()}
    calls=[];monkeypatch.setattr(workspace,'request',lambda *a,**kw:calls.append(a) or rotated)
    r=client.post(f'/api/v1/workspace/accounts/{a["id"]}/refresh',headers=headers)
    assert calls and r.json()['status']=='awaiting_scan' and r.json()['qr_available']


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


def test_douyin_login_detection_requires_session_cookie():
    import asyncio
    import types
    from app.login_adapter import BrowserManager, PLATFORM_CONFIG
    assert 'url_contains' not in PLATFORM_CONFIG['douyin']

    class Page:
        url='https://creator.douyin.com/creator-micro/home'
        def is_closed(self):return False
    class Context:
        def __init__(self,cookies):self.value=cookies
        async def cookies(self):return self.value
    session=types.SimpleNamespace(page=Page(),platform='douyin',context=Context([]))
    manager=BrowserManager()
    assert asyncio.run(manager._logged_in(session)) is False
    session.context=Context([{'name':'sessionid','value':'x'*32}])
    assert asyncio.run(manager._logged_in(session)) is True


def test_qr_like_rejects_promo_banner_and_colorful_image():
    import io
    from PIL import Image, ImageDraw
    from app.login_adapter import _qr_like

    def png(image):
        out=io.BytesIO();image.save(out,'PNG');return out.getvalue()

    code=Image.new('RGB',(256,256),'white');draw=ImageDraw.Draw(code)
    for x in range(16,240,16):
        for y in range(16,240,16):
            if (x//16+y//16)%2==0:draw.rectangle([x,y,x+14,y+14],fill='black')
    assert _qr_like(png(code)) is True

    # 登录页 4:3 推广轮播：即使主体是黑白也不能当二维码。
    banner=Image.new('RGB',(480,360),'white')
    ImageDraw.Draw(banner).rectangle([30,30,450,330],fill='black')
    assert _qr_like(png(banner)) is False

    # 正方形但颜色丰富的宣传图同样拒绝。
    promo=Image.new('RGB',(300,300),(230,60,40))
    ImageDraw.Draw(promo).rectangle([20,20,140,140],fill=(30,90,200))
    assert _qr_like(png(promo)) is False


def test_refresh_extends_expiry_when_platform_rotates_qr(monkeypatch):
    import asyncio,io
    from PIL import Image
    from app import login_adapter
    from app.login_adapter import BrowserManager, _Session

    def raw(color):
        out=io.BytesIO();Image.new('RGB',(180,180),color).save(out,'PNG');return out.getvalue()

    class Page:
        url='https://creator.douyin.com/creator-micro/home'
        def is_closed(self):return False
        async def evaluate(self,_):return ''
    class Context:
        async def cookies(self):return []
        async def close(self):pass

    old,new=raw('white'),raw('black')
    manager=BrowserManager()
    session=_Session(1,'douyin','attempt',Context(),Page(),old,
                     login_adapter._now()-timedelta(seconds=5))
    manager._sessions[1]=session
    async def fresh(_, selector=''):return new
    monkeypatch.setattr(login_adapter,'_qr_from_page',fresh)
    data=asyncio.run(manager.refresh(1,'attempt'))
    assert data['status']=='awaiting_scan'
    assert data['qr_png_base64']==base64.b64encode(new).decode()
    assert session.expires_at>login_adapter._now()


def test_session_import_encrypts_cookies_and_audits(client,headers,monkeypatch):
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    a=account(client,headers);seen=[]
    expires=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
    def adapter(action,payload,request_key=None):
        seen.append((action,payload))
        return {'ok':True,'status':'connected','session':{'handle':'imported-handle'},
                'nickname':'本机扫码账号','expires_at':expires}
    monkeypatch.setattr(workspace,'request',adapter)
    body={'platform':'douyin','session':{'cookies':[
        {'name':'sessionid','value':'s'*64,'domain':'.douyin.com','path':'/','secure':True,
         'httpOnly':True,'sameSite':'no_restriction','expirationDate':4102444800},
        {'name':'sessionid_ss','value':'t'*64,'domain':'.douyin.com','path':'/','secure':True},
    ],'nickname':'备用昵称'}}
    r=client.post(f'/api/v1/workspace/accounts/{a["id"]}/session-import',headers=headers,json=body)
    assert r.status_code==200,r.text
    data=r.json()
    assert data['status']=='connected' and data['nickname']=='本机扫码账号'
    assert 'session_ciphertext' not in data and 's'*64 not in r.text and 't'*64 not in r.text
    assert seen[0][0]=='accounts/import' and seen[0][1]['cookies'][0]['name']=='sessionid'
    # 适配器收到的 Cookie 已规范化：Chrome 的 no_restriction 转成 Playwright 的 None。
    assert seen[0][1]['cookies'][0]['sameSite']=='None'
    with SessionLocal() as db:
        row=db.get(WorkspaceAccount,a['id'])
        payload=workspace.decrypt(row.session_ciphertext)
        assert payload['handle']=='imported-handle' and payload['source']=='cookie_import'
        assert payload['cookies'][0]['value']=='s'*64
        ev=db.scalar(select(AutomationEvent).where(AutomationEvent.action=='session_import'))
        assert ev and ev.detail['cookie_count']==2
        assert 's'*64 not in str(ev.detail) and 't'*64 not in str(ev.detail)


def test_session_import_rejects_wrong_platform_and_missing_cookie(client,headers,monkeypatch):
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    a=account(client,headers)
    monkeypatch.setattr(workspace,'request',lambda *args,**kw:pytest.fail('校验前不得调用适配器'))
    wrong=client.post(f'/api/v1/workspace/accounts/{a["id"]}/session-import',headers=headers,
        json={'platform':'xhs','session':{'cookies':[{'name':'sessionid','value':'x'*20,'domain':'.douyin.com'}]}})
    assert wrong.status_code==409
    missing=client.post(f'/api/v1/workspace/accounts/{a["id"]}/session-import',headers=headers,
        json={'platform':'douyin','session':{'cookies':[{'name':'ttwid','value':'x'*20,'domain':'.douyin.com'}]}})
    assert missing.status_code==422 and 'sessionid' in missing.text
    foreign=client.post(f'/api/v1/workspace/accounts/{a["id"]}/session-import',headers=headers,
        json={'platform':'douyin','session':{'cookies':[{'name':'sessionid','value':'x'*20,'domain':'.example.com'}]}})
    assert foreign.status_code==422


def test_session_import_requires_adapter_verification(client,headers,monkeypatch):
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    a=account(client,headers)
    monkeypatch.setattr(workspace,'request',lambda *args,**kw:{'ok':True,'status':'invalid','error':'Cookie 已失效'})
    r=client.post(f'/api/v1/workspace/accounts/{a["id"]}/session-import',headers=headers,
        json={'platform':'douyin','session':{'cookies':[{'name':'sessionid','value':'x'*20,'domain':'.douyin.com'}]}})
    assert r.status_code==422 and 'Cookie 已失效' in r.text
    with SessionLocal() as db:
        row=db.get(WorkspaceAccount,a['id'])
        assert row.status=='disconnected' and not row.session_ciphertext
        assert db.scalar(select(AutomationEvent).where(AutomationEvent.action=='session_import')) is None


def test_refresh_restores_imported_session_after_adapter_restart(monkeypatch):
    import asyncio
    from app.login_adapter import BrowserManager
    manager=BrowserManager();called=[]
    async def restore(account_id,platform,cookies):
        called.append((account_id,platform,cookies))
        return {'ok':True,'status':'connected','session':{'handle':'restored'},
                'nickname':'恢复账号','expires_at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()}
    monkeypatch.setattr(manager,'_import_locked',restore)
    data=asyncio.run(manager.refresh(1,'',{'cookies':[{'name':'sessionid','value':'x'}]},'douyin'))
    assert data['status']=='connected' and data['session']['handle']=='restored'
    assert called and called[0][:2]==(1,'douyin')


def test_refresh_accepts_late_phone_confirmation_after_qr_expiry(monkeypatch):
    import asyncio,io
    from PIL import Image
    from app import login_adapter
    from app.login_adapter import BrowserManager, _Session

    out=io.BytesIO();Image.new('RGB',(180,180),'white').save(out,'PNG')
    class Page:
        url='https://creator.douyin.com/creator-micro/home'
        def is_closed(self):return False
        async def evaluate(self,_):return ''
    class Context:
        async def cookies(self):return [{'name':'sessionid','value':'x'*32}]
        async def close(self):pass

    manager=BrowserManager()
    session=_Session(1,'douyin','attempt',Context(),Page(),out.getvalue(),
                     login_adapter._now()-timedelta(seconds=5))
    manager._sessions[1]=session
    async def fail(_, selector=''):raise AssertionError('登录态检查必须先于二维码续期')
    monkeypatch.setattr(login_adapter,'_qr_from_page',fail)
    data=asyncio.run(manager.refresh(1,'attempt'))
    assert data['status']=='connected' and data['session']['handle']

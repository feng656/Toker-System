"""二期契约/安全回归。外部平台均为明确的适配替身，绝非真实送达验收。"""
import base64
import hashlib
import json
from datetime import timedelta, datetime, timezone
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from app import config, workspace, media, engagement, login_security
from app.db import SessionLocal, utcnow
from app.models import (WorkspaceAccount, LoginBucket, AuthChallenge, ContentVariant,
                        CommentAction, Platform, DMMessage, AIJob)
from .conftest import generated, token_for


def post(client, headers, path, data=None, status=200):
    r=client.post('/api/v1'+path,headers=headers,json={} if data is None else data)
    assert r.status_code==status,r.text
    return r.json()


def platforms(client, headers):
    return client.get('/api/v1/platforms',headers=headers).json()


@pytest.fixture
def connected(client,headers,monkeypatch):
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.setattr(config,'AUTOMATION_ENABLED',True)
    monkeypatch.setattr(config,'AUTOMATION_INTERVAL_SECONDS',0)
    aid=post(client,headers,'/workspace/accounts',{'platform_id':platforms(client,headers)[0]['id'],'label':'测试账号'},201)['id']
    with SessionLocal() as db:
        a=db.get(WorkspaceAccount,aid);a.status='connected';a.session_ciphertext=workspace.encrypt({'opaque_session':'secret-session'})
        a.session_expires_at=utcnow()+timedelta(hours=1);db.commit()
    return aid


def test_dynamic_platform_generation_filters_and_history(client,headers):
    p=next(x for x in platforms(client,headers) if x['code']=='taobao')
    response=client.put(f'/api/v1/platforms/{p["id"]}',headers=headers,json={'code':'taobao','name':'淘宝','category':'commerce','style_prompt':'明确规格','generation_enabled':True,'expected_version':p['version']})
    assert response.status_code==200,response.text
    p=response.json()
    vs=generated(client,headers)
    assert len(vs)==10
    matches=client.get('/api/v1/variants',params={'platform_id':p['id']},headers=headers).json()
    assert matches['total']==2 and all(v['platform']=='taobao' for v in matches['items'])
    response=client.put(f'/api/v1/platforms/{p["id"]}',json={'code':'taobao','name':'淘宝','enabled':False,'expected_version':p['version']},headers=headers)
    assert response.status_code==200
    assert len(client.get('/api/v1/contents',headers=headers).json())==2
    assert any(x['platform_id']==p['id'] for x in client.get('/api/v1/dashboard/platforms',headers=headers).json())
    assert client.get('/api/platforms',headers=headers).headers['deprecation']=='true'


def test_platform_code_immutable_roles_and_invalid_codes(client,headers):
    p=platforms(client,headers)[0]
    assert client.put(f'/api/v1/platforms/{p["id"]}',json={'code':'renamed','name':'改名'},headers=headers).status_code==409
    assert client.post('/api/v1/platforms',json={'code':'../private','name':'坏代码'},headers=headers).status_code==422
    sales=token_for(client,'sales01')
    for path in ('/platforms','/workspace/accounts','/assets','/dm/messages','/automation/events'):
        assert client.get('/api/v1'+path,headers=sales).status_code==403


def test_bulk_whole_batch_precheck_and_version_conflict(client,headers):
    vs=generated(client,headers)[:2]
    with SessionLocal() as db:
        bad=db.get(ContentVariant,vs[1]['id']);bad.body='全国第一';bad.status='blocked';db.commit();vs[1]['version']=bad.version
    data={'variant_ids':[v['id'] for v in vs],'action':'approve','expected_versions':{str(v['id']):v['version'] for v in vs}}
    assert client.post('/api/v1/variants/bulk-review',json=data,headers=headers).status_code==409
    with SessionLocal() as db:assert db.get(ContentVariant,vs[0]['id']).confirm_status!='confirmed'
    data={'variant_ids':[vs[0]['id']],'action':'approve','expected_versions':{str(vs[0]['id']):999}}
    assert client.post('/api/v1/variants/bulk-review',json=data,headers=headers).status_code==409
    data['expected_versions']={}
    assert client.post('/api/v1/variants/bulk-review',json=data,headers=headers).status_code==422


def test_bulk_approve_reject_history(client,headers):
    vs=generated(client,headers)[:2]
    data={'variant_ids':[v['id'] for v in vs],'action':'approve','expected_versions':{str(v['id']):v['version'] for v in vs}}
    result=post(client,headers,'/variants/bulk-review',data)
    assert result['processed']==2
    now=client.get(f'/api/v1/variants/{vs[0]["id"]}',headers=headers).json()
    result=post(client,headers,'/variants/bulk-review',{'variant_ids':[now['id']],'action':'reject','reason':'突出服务边界', 'expected_versions':{str(now['id']):now['version']}})
    assert result['items'][0]['new_variant_id']
    history=client.get(f'/api/v1/variants/{now["id"]}/history',headers=headers).json()
    assert len(history)==2 and history[0]['rejection_reason']=='突出服务边界'


def test_assets_validate_private_permissions_generate_usage(client,headers,image_bytes,fake_storage,monkeypatch):
    r=client.post('/api/v1/assets/upload',files=[('files',('a.png',image_bytes,'image/png')),('files',('b.png',b'not-image','image/png'))],headers=headers)
    assert r.status_code==422 and not fake_storage
    r=client.post('/api/v1/assets/upload',files=[('files',('a.png',image_bytes,'image/png'))],headers=headers)
    assert r.status_code==201,r.text
    asset=r.json()['items'][0]
    topic=client.get('/api/v1/topics',headers=headers).json()[0]
    payload={'request_key':'asset-gen','topic_id':topic['id'],'platform_id':platforms(client,headers)[0]['id'],'asset_ids':[asset['id']]}
    assert client.post('/api/v1/assets/generate-content',json=payload,headers=headers).status_code==409
    assert client.put(f'/api/v1/assets/{asset["id"]}',json={'title':'产品实拍','publicity':'public','tags':'LED'},headers=headers).status_code==200
    result=post(client,headers,'/assets/generate-content',payload,201)
    again=post(client,headers,'/assets/generate-content',payload,201)
    assert result['id']==again['id']
    usage=client.get(f'/api/v1/assets/{asset["id"]}/usage',headers=headers).json()
    assert len(usage)==1
    monkeypatch.setattr('app.storage.signed_url',lambda ref:'https://storage.invalid/signed')
    assert client.get(f'/api/v1/assets/{asset["id"]}/url',headers=headers).status_code==200


def test_manual_draft_needs_quality_and_review(client,headers):
    p=platforms(client,headers)[0]
    c=post(client,headers,'/contents/drafts',{'title':'人工内容','platform_id':p['id'],'body':'按项目需求核实产品，私信询价'},201)
    vid=c['variants'][0]['id']
    assert client.post(f'/api/v1/variants/{vid}/approve',json={},headers=headers).status_code==409
    post(client,headers,f'/variants/{vid}/quality')
    post(client,headers,f'/variants/{vid}/approve')


def test_ai_providers_secret_references_and_ssrf(client,headers,monkeypatch):
    monkeypatch.setattr(config,'ADAPTER_ALLOWED_HOSTS',['ai.example.net'])
    monkeypatch.setenv('TOKER_AI_KEY_TEXT','never-return-this-key')
    payload={'name':'text-test','endpoint':'https://ai.example.net/v1','model':'test','key_env':'TOKER_AI_KEY_TEXT'}
    p=post(client,headers,'/ai/providers',payload,201)
    assert p['configured'] and 'never-return-this-key' not in json.dumps(p)
    assert client.post('/api/v1/ai/providers',json={**payload,'name':'bad','endpoint':'http://127.0.0.1'},headers=headers).status_code==422
    assert client.post('/api/v1/ai/providers',json={**payload,'name':'bad','endpoint':'https://ai.example.net/v1?token=secret'},headers=headers).status_code==422
    assert client.post('/api/v1/ai/providers',json={**payload,'name':'bad','api_key':'secret'},headers=headers).status_code==422
    response=client.get('/api/v1/llm/status',headers=headers).json()
    assert response['configured'] and response['providers'][0]['name']=='text-test'


def test_login_invite_off_then_lowest_role(client,monkeypatch):
    data={'username':'new-person','password':'a-secure-new-password','invite_code':'z'*20}
    assert client.post('/api/v1/auth/login',json=data).status_code==401
    with SessionLocal() as db:
        for b in db.scalars(select(LoginBucket)).all():b.blocked_until=None
        db.commit()
    monkeypatch.setattr(config,'AUTO_REGISTER_MODE','invite');monkeypatch.setattr(config,'REGISTER_INVITE_CODE','z'*20)
    r=client.post('/api/v1/auth/login',json=data)
    assert r.status_code==200,r.text
    assert r.json()['user']['role']=='sales'
    bad=client.post('/api/v1/auth/login',json={'username':'x','password':'s'*80})
    assert bad.status_code==422 and 's'*80 not in bad.text


def test_login_throttle_and_one_use_ip_bound_challenge(client,monkeypatch):
    monkeypatch.setattr(config,'LOGIN_IP_LIMIT',2)
    assert client.post('/api/v1/auth/challenge').status_code==200
    assert client.post('/api/v1/auth/challenge').status_code==200
    response=client.post('/api/v1/auth/challenge')
    assert response.status_code==429 and response.headers['retry-after']
    monkeypatch.setattr(config,'LOGIN_IP_LIMIT',100)
    data=client.post('/api/v1/auth/challenge').json()
    solution=next(str(i) for i in range(1000000) if hashlib.sha256((data['nonce']+str(i)).encode()).hexdigest().startswith('0'*data['difficulty']))
    from app.schemas import LoginIn
    body=LoginIn(username='x',password='x',challenge_id=data['challenge_id'],challenge_solution=solution)
    with SessionLocal() as db:
        assert not login_security.verify_challenge(db,body,'wrong-ip')
        assert login_security.verify_challenge(db,body,'testclient')
        assert not login_security.verify_challenge(db,body,'testclient')


def test_login_inflight_gate_does_not_hash(client,monkeypatch):
    import threading
    gate=threading.BoundedSemaphore(1);gate.acquire()
    monkeypatch.setattr(login_security,'_gate',gate)
    monkeypatch.setattr(login_security,'verify_password',lambda *_:pytest.fail('拥塞时不能计算密码哈希'))
    assert client.post('/api/v1/auth/login',json={'username':'x','password':'wrong'}).status_code==429


def test_real_adapter_missing_no_fake_qr(client,headers,monkeypatch):
    monkeypatch.setattr(config,'SESSION_ENCRYPTION_KEY',Fernet.generate_key().decode())
    monkeypatch.setattr(config,'BROWSER_ENABLED',False)
    a=post(client,headers,'/workspace/accounts',{'platform_id':platforms(client,headers)[0]['id'],'label':'未登录'},201)
    assert client.post(f'/api/v1/workspace/accounts/{a["id"]}/login',json={},headers=headers).status_code==503
    assert not client.get(f'/api/v1/workspace/accounts/{a["id"]}/session',headers=headers).json()['qr_available']


def test_qr_login_encrypted_session_refresh_and_expiry(client,headers,connected,image_bytes,fake_storage,monkeypatch):
    expiry=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()
    monkeypatch.setattr(workspace,'request',lambda *a,**k:{'ok':True,'status':'awaiting_scan','attempt_id':'attempt','qr_png_base64':base64.b64encode(image_bytes).decode(),'expires_at':expiry})
    qr=post(client,headers,f'/workspace/accounts/{connected}/login')
    assert qr['qr_available'] and 'session_ciphertext' not in qr
    monkeypatch.setattr(workspace,'request',lambda *a,**k:{'ok':True,'status':'connected','session':{'opaque':'do-not-return'},'nickname':'测试账号','expires_at':expiry})
    result=post(client,headers,f'/workspace/accounts/{connected}/refresh')
    assert result['status']=='connected' and 'do-not-return' not in json.dumps(result)
    with SessionLocal() as db:
        a=db.get(WorkspaceAccount,connected);assert 'do-not-return' not in a.session_ciphertext
        a.session_expires_at=utcnow()-timedelta(seconds=1);db.commit()
    assert client.get(f'/api/v1/workspace/accounts/{connected}/session',headers=headers).json()['status']=='expired'


def test_publish_preparation_confirmation_and_idempotence(client,headers,connected,image_bytes,fake_storage,monkeypatch):
    v=generated(client,headers)[0];post(client,headers,f'/variants/{v["id"]}/approve')
    j=post(client,headers,'/workspace/publish-jobs',{'request_key':'publish-1','account_id':connected,'variant_id':v['id']},201)
    evidence=[{'name':'preview','status':'ok','screenshot_png_base64':base64.b64encode(image_bytes).decode()}]
    calls=[]
    def adapter(action,payload,key=None):
        calls.append((action,key))
        if action=='publish/prepare':
            assert payload['submit'] is False
            return {'ok':True,'status':'awaiting_confirmation','job_id':'remote','confirmation_token':'sensitive','steps':evidence}
        assert payload['human_confirmed'] is True
        return {'ok':True,'status':'published','url':'https://www.douyin.com/video/1234567','steps':evidence}
    monkeypatch.setattr(workspace,'request',adapter)
    assert post(client,headers,f'/workspace/publish-jobs/{j["id"]}/run')['status']=='awaiting_confirmation'
    assert client.get(f'/api/v1/variants/{v["id"]}',headers=headers).json()['status']!='published'
    assert post(client,headers,f'/workspace/publish-jobs/{j["id"]}/confirm')['status']=='succeeded'
    assert post(client,headers,f'/workspace/publish-jobs/{j["id"]}/confirm')['status']=='succeeded'
    assert len(calls)==2 and len(fake_storage)==2


def test_publish_revalidates_draft_after_preview(client,headers,connected,image_bytes,fake_storage,monkeypatch):
    v=generated(client,headers)[0];post(client,headers,f'/variants/{v["id"]}/approve')
    j=post(client,headers,'/workspace/publish-jobs',{'request_key':'publish-change','account_id':connected,'variant_id':v['id']},201)
    monkeypatch.setattr(workspace,'request',lambda *a,**k:{'ok':True,'status':'awaiting_confirmation','job_id':'remote','confirmation_token':'token', 'steps':[{'screenshot_png_base64':base64.b64encode(image_bytes).decode()}]})
    post(client,headers,f'/workspace/publish-jobs/{j["id"]}/run')
    assert client.put(f'/api/v1/variants/{v["id"]}',headers=headers,json={'body':'修改后正文，私信询价'}).status_code==200
    assert client.post(f'/api/v1/workspace/publish-jobs/{j["id"]}/confirm',headers=headers).status_code==409


def test_video_never_accepts_remote_id_as_asset(client,headers,monkeypatch,fake_storage):
    monkeypatch.setattr(config,'ADAPTER_ALLOWED_HOSTS',['video.example.net'])
    p=post(client,headers,'/ai/providers',{'name':'video','capability':'video','endpoint':'https://video.example.net','model':'test'},201)
    j=post(client,headers,'/video-jobs',{'request_key':'video-one','prompt':'产品演示','provider_id':p['id']},201)
    monkeypatch.setattr(media,'video_request',lambda *a,**k:{'job_id':'remote-1','status':'running'})
    assert post(client,headers,f'/video-jobs/{j["id"]}/run')['output_asset_id'] is None
    monkeypatch.setattr(media,'video_request',lambda *a,**k:{'status':'succeeded','output_url':'https://cdn.example.net/video.mp4'})
    monkeypatch.setattr(media,'download_video',lambda *_:b'not-real-video')
    assert post(client,headers,f'/video-jobs/{j["id"]}/run')['status']=='failed'
    assert not fake_storage


def test_video_success_validated_and_asset_created_once(client,headers,monkeypatch,fake_storage,tmp_path):
    import subprocess
    output=tmp_path/'test.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:d=0.5','-c:v','libx264','-pix_fmt','yuv420p',str(output)],check=True)
    data=output.read_bytes()
    assert media.validate_video(data)=='video/mp4'
    monkeypatch.setattr(config,'ADAPTER_ALLOWED_HOSTS',['video.example.net'])
    p=post(client,headers,'/ai/providers',{'name':'video','capability':'video','endpoint':'https://video.example.net','model':'test'},201)
    j=post(client,headers,'/video-jobs',{'request_key':'video-ok','prompt':'test','provider_id':p['id']},201)
    monkeypatch.setattr(media,'video_request',lambda *a,**k:{'job_id':'job','status':'succeeded','output_url':'https://cdn.example.net/video.mp4'})
    monkeypatch.setattr(media,'download_video',lambda *_:data)
    result=post(client,headers,f'/video-jobs/{j["id"]}/run')
    assert result['status']=='succeeded' and result['output_asset_id']
    post(client,headers,f'/video-jobs/{j["id"]}/run');assert len(fake_storage)==1


def make_comments(client,headers,connected,monkeypatch):
    task=post(client,headers,'/comment-tasks',{'account_id':connected,'keyword':'LED应用','mode':'manual','draft':'这个场景如何选择合适的显示方案？欢迎私信询价'},201)
    monkeypatch.setattr(workspace,'request',lambda *a,**k:{'ok':True,'targets':[{'id':'video1','url':'https://www.douyin.com/video/111','authorized':True,'authorization_ref':'owned-target-1'}]})
    post(client,headers,f'/comment-tasks/{task["id"]}/discover',{'search_confirmed':True})
    post(client,headers,f'/comment-tasks/{task["id"]}/prepare')
    return task['id']


def test_comment_approval_limits_send_collect_and_suggestions(client,headers,connected,monkeypatch):
    tid=make_comments(client,headers,connected,monkeypatch)
    assert client.post(f'/api/v1/comment-tasks/{tid}/run',headers=headers).status_code==409
    post(client,headers,f'/comment-tasks/{tid}/approve')
    calls=[]
    def adapter(action,payload,key=None):
        calls.append(action)
        if action=='comments/send':return {'ok':True,'status':'sent','comment_id':'sent-1'}
        return {'ok':True,'replies':[{'id':'r1','parent_comment_id':'sent-1','sender_id':'buyer','body':'有学校项目需要报价，电话13800138000'}]}
    monkeypatch.setattr(workspace,'request',adapter)
    assert post(client,headers,f'/comment-tasks/{tid}/run')['status']=='succeeded'
    post(client,headers,f'/comment-tasks/{tid}/run');assert calls.count('comments/send')==1
    post(client,headers,f'/comment-tasks/{tid}/collect');post(client,headers,f'/comment-tasks/{tid}/collect')
    suggestions=client.get('/api/v1/topic-suggestions',headers=headers).json();assert len(suggestions)==1
    one=post(client,headers,f'/topic-suggestions/{suggestions[0]["id"]}/convert')
    assert post(client,headers,f'/topic-suggestions/{suggestions[0]["id"]}/convert')==one
    leads=client.get('/api/v1/leads',headers=headers).json();assert len(leads)==1 and '13800138000' not in json.dumps(leads)
    assert client.post('/api/v1/comment-tasks',json={'account_id':connected,'keyword':'x','video_limit':6},headers=headers).status_code==422


def test_comment_stop_history_dedup_and_unauthorized_target(client,headers,connected,monkeypatch):
    tid=make_comments(client,headers,connected,monkeypatch)
    post(client,headers,f'/comment-tasks/{tid}/approve');post(client,headers,f'/comment-tasks/{tid}/stop')
    assert client.post(f'/api/v1/comment-tasks/{tid}/run',headers=headers).status_code==409
    second=make_comments(client,headers,connected,monkeypatch)
    assert client.get(f'/api/v1/comment-tasks/{second}',headers=headers).json()['actions']==[]
    task=post(client,headers,'/comment-tasks',{'account_id':connected,'keyword':'x','mode':'ai'},201)
    monkeypatch.setattr(workspace,'request',lambda *a,**k:{'ok':True,'targets':[{'id':'x','url':'https://www.douyin.com/video/111','authorized':False}]})
    assert client.post(f'/api/v1/comment-tasks/{task["id"]}/discover',json={'search_confirmed':True},headers=headers).status_code==409


def setup_dm(client,headers,connected,mode='fixed'):
    t=post(client,headers,'/reply-templates',{'name':'标准答复','body':'感谢咨询，请说明项目场景，私信询价。'},201)
    post(client,headers,'/dm-policies',{'account_id':connected,'mode':mode,'template_id':t['id'],'window_start':'00:00','window_end':'23:59','scope':['buyer'],'enabled':True})
    return post(client,headers,'/dm/messages',{'source_key':'incoming','account_id':connected,'sender_id':'buyer','body':'项目报价需求'},201)


def test_dm_fixed_approval_scope_idempotency_and_audit(client,headers,connected,monkeypatch):
    m=setup_dm(client,headers,connected)
    assert post(client,headers,'/dm/messages',{'source_key':'incoming','account_id':connected,'sender_id':'buyer','body':'项目报价需求'},201)['id']==m['id']
    assert post(client,headers,f'/dm/messages/{m["id"]}/prepare')['status']=='pending_review'
    assert client.post(f'/api/v1/dm/messages/{m["id"]}/send',headers=headers).status_code==409
    post(client,headers,f'/dm/messages/{m["id"]}/approve')
    calls=[]
    monkeypatch.setattr(workspace,'request',lambda *a,**k:calls.append(a) or {'ok':True,'status':'sent','message_id':'remote-dm'})
    assert post(client,headers,f'/dm/messages/{m["id"]}/send')['status']=='sent'
    post(client,headers,f'/dm/messages/{m["id"]}/send');assert len(calls)==1
    events=client.get('/api/v1/automation/events',params={'resource':'dm','resource_id':m['id']},headers=headers).json()
    assert {'received','pending_review','approve','sent'} <= {e['action'] for e in events}


def test_dm_high_risk_escalates_and_ai_candidate_requires_approval(client,headers,connected,monkeypatch):
    setup_dm(client,headers,connected,'ai')
    m=post(client,headers,'/dm/messages',{'source_key':'risk','account_id':connected,'sender_id':'buyer','body':'请提供银行卡和验证码'},201)
    assert post(client,headers,f'/dm/messages/{m["id"]}/prepare')['status']=='escalated'
    assert client.post(f'/api/v1/dm/messages/{m["id"]}/approve',headers=headers).status_code==409
    outsider=post(client,headers,'/dm/messages',{'source_key':'other','account_id':connected,'sender_id':'stranger','body':'你好'},201)
    assert client.post(f'/api/v1/dm/messages/{outsider["id"]}/prepare',headers=headers).status_code==409
    monkeypatch.setattr(engagement,'call_json',lambda *a,**k:{'reply':'感谢咨询，请补充项目场景，私信询价。'})
    messages=client.get('/api/v1/dm/messages',headers=headers).json()
    original=next(x for x in messages if x['body']=='项目报价需求')
    assert post(client,headers,f'/dm/messages/{original["id"]}/prepare')['status']=='pending_review'


def test_automation_daily_budget_and_default_off(client,headers,connected,monkeypatch):
    tid=make_comments(client,headers,connected,monkeypatch);post(client,headers,f'/comment-tasks/{tid}/approve')
    monkeypatch.setattr(config,'AUTOMATION_ENABLED',False)
    assert client.post(f'/api/v1/comment-tasks/{tid}/run',headers=headers).status_code==503
    monkeypatch.setattr(config,'AUTOMATION_ENABLED',True);monkeypatch.setattr(config,'AUTOMATION_DAILY_LIMIT',0)
    assert client.post(f'/api/v1/comment-tasks/{tid}/run',headers=headers).status_code==429

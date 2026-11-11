"""HTTP适配契约测试：真实HTTP客户端+模拟传输，不访问真实平台。"""
import httpx
import respx
import pytest
from fastapi import HTTPException
from app import config, workspace, media
from app.db import SessionLocal
from app.models import AIProvider
from app.llm import call_json
from .test_phase2 import post, connected, setup_dm


@respx.mock
def test_browser_http_auth_idempotency_and_no_redirect(monkeypatch):
    monkeypatch.setattr(config,'BROWSER_ENABLED',True)
    monkeypatch.setattr(config,'BROWSER_ADAPTER_URL','https://adapter.example.test')
    monkeypatch.setattr(config,'BROWSER_ADAPTER_TOKEN','secret-test')
    monkeypatch.setattr(config,'ADAPTER_ALLOWED_HOSTS',['adapter.example.test'])
    route=respx.post('https://adapter.example.test/v2/comments/send').mock(return_value=httpx.Response(200,json={'ok':True,'status':'sent','comment_id':'id'}))
    assert workspace.request('comments/send',{'account_id':1},'stable-key')['status']=='sent'
    assert route.calls.last.request.headers['Idempotency-Key']=='stable-key'
    assert route.calls.last.request.headers['Authorization']=='Bearer secret-test'
    route.mock(return_value=httpx.Response(302,headers={'Location':'http://127.0.0.1/secret'}))
    with pytest.raises(HTTPException) as exc:workspace.request('comments/send',{})
    assert exc.value.status_code==502


@respx.mock
def test_database_ai_provider_selected_and_fallback(monkeypatch):
    monkeypatch.setattr(config,'DEMO_MODE',False)
    monkeypatch.setattr(config,'ADAPTER_ALLOWED_HOSTS',['one.example.test','two.example.test'])
    monkeypatch.setenv('TOKER_AI_KEY_TEST','private-value')
    with SessionLocal() as db:
        for rank,host in enumerate(('one.example.test','two.example.test')):
            db.add(AIProvider(name=host,capability='text',endpoint='https://'+host,model='test',key_env='TOKER_AI_KEY_TEST',priority=rank))
        db.commit()
        respx.post('https://one.example.test/chat/completions').mock(return_value=httpx.Response(503))
        good=respx.post('https://two.example.test/chat/completions').mock(return_value=httpx.Response(200,json={'choices':[{'message':{'content':'{"reply":"ok"}'}}]}))
        assert call_json(db,'dm_reply','system','input')=={'reply':'ok'}
        assert good.calls.last.request.headers['Authorization']=='Bearer private-value'


@respx.mock
def test_video_http_rejection_failover(client,headers,monkeypatch):
    monkeypatch.setattr(config,'ADAPTER_ALLOWED_HOSTS',['video-one.test','video-two.test'])
    for host in ('video-one.test','video-two.test'):
        post(client,headers,'/ai/providers',{'name':host,'endpoint':'https://'+host,'capability':'video','model':'test'},201)
    respx.post('https://video-one.test/jobs').mock(return_value=httpx.Response(503))
    second=respx.post('https://video-two.test/jobs').mock(return_value=httpx.Response(200,json={'job_id':'accepted','status':'running'}))
    job=post(client,headers,'/video-jobs',{'request_key':'failover','prompt':'test'},201)
    result=post(client,headers,f'/video-jobs/{job["id"]}/run')
    assert result['status']=='running' and result['remote_job_id']=='accepted'
    assert second.calls.last.request.headers['Idempotency-Key']=='video:failover'


def test_worker_only_sends_approved_dm(client,headers,connected,monkeypatch):
    from app.phase2_worker import tick
    m=setup_dm(client,headers,connected)
    post(client,headers,f'/dm/messages/{m["id"]}/prepare')
    monkeypatch.setattr(config,'PHASE2_WORKER_ENABLED',True)
    calls=[]
    monkeypatch.setattr(workspace,'request',lambda *a,**k:calls.append(a) or {'ok':True,'status':'sent','message_id':'worker-reply'})
    tick();assert calls==[]
    post(client,headers,f'/dm/messages/{m["id"]}/approve')
    tick();assert len(calls)==1
    tick();assert len(calls)==1

from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import select
from app import config, workspace, engagement
from app.db import SessionLocal, utcnow
from app.models import DMMessage, CommentAction, WorkspaceAccount, AutomationEvent
from .test_phase2 import connected, post, setup_dm, make_comments


def test_worker_recovery_marks_uncertain_never_auto_replays(client,headers,connected,monkeypatch):
    from app.phase2_worker import recover,tick
    m=setup_dm(client,headers,connected)
    with SessionLocal() as db:
        msg=db.get(DMMessage,m['id']);msg.status='sending';msg.updated_at=utcnow()-timedelta(minutes=20);db.commit()
    with SessionLocal() as db:
        assert recover(db)==1
        assert db.get(DMMessage,m['id']).status=='uncertain'
    monkeypatch.setattr(config,'PHASE2_WORKER_ENABLED',True)
    monkeypatch.setattr(workspace,'request',lambda *_:pytest.fail('结果不确定不能自动重发'))
    tick()


def test_comment_uncertain_uses_same_key_and_blocks_next_sending(client,headers,connected,monkeypatch):
    tid=make_comments(client,headers,connected,monkeypatch)
    post(client,headers,f'/comment-tasks/{tid}/approve')
    calls=[]
    def fail(action,payload,key=None):
        calls.append(key);raise RuntimeError('timeout')
    monkeypatch.setattr(workspace,'request',fail)
    result=post(client,headers,f'/comment-tasks/{tid}/run')
    assert result['actions'][0]['status']=='uncertain'
    monkeypatch.setattr(workspace,'request',lambda action,payload,key=None:calls.append(key) or {'status':'sent','comment_id':'same','ok':True})
    post(client,headers,f'/comment-tasks/{tid}/run')
    assert len(calls)==2 and calls[0]==calls[1]


def test_mirror_default_dry_run_no_force_no_delete(monkeypatch):
    from scripts import sync_mirror
    calls=[]
    def git(*args):
        calls.append(args)
        return 'a'*40 if args[0]=='rev-parse' else ''
    monkeypatch.setattr(sync_mirror,'git',git)
    assert sync_mirror.sync('https://gitee.com/org/repo.git','main')['mode']=='dry-run'
    assert '--dry-run' in calls[-1] and not any('force' in x or 'delete' in x or x=='--mirror' for call in calls for x in call)
    for target in ('http://gitee.com/org/repo','https://token@gitee.com/org/repo','https://other.com/org/repo'):
        with pytest.raises(ValueError):sync_mirror.validate_target(target)


def test_login_concurrent_failfast_gate(client,monkeypatch):
    import threading
    from app import login_security
    gate=threading.BoundedSemaphore(1);gate.acquire();monkeypatch.setattr(login_security,'_gate',gate)
    with ThreadPoolExecutor(max_workers=16) as pool:
        statuses=list(pool.map(lambda _:client.post('/api/v1/auth/login',json={'username':'x','password':'wrong'}).status_code,range(64)))
    assert statuses==[429]*64
    assert client.get('/api/v1/health').status_code==200

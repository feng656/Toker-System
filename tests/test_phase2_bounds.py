"""边界验证使用明确准备好的候选和传输替身，不产生真实评论。"""
from sqlalchemy import select
from app import config,workspace
from app.db import SessionLocal
from app.models import CommentTask,CommentAction
from .test_phase2 import connected,post


def test_bounded_five_by_ten_prepared_actions_no_duplicate_send(client,headers,connected,monkeypatch):
    task=post(client,headers,'/comment-tasks',{'account_id':connected,'keyword':'受控测试','mode':'ai'},201)
    # 本测试只验50条队列限额/幂等，不把数据库测试候选冒充AI文案质量验收。
    with SessionLocal() as db:
        t=db.get(CommentTask,task['id'])
        t.targets=[{'id':f'owned-{i}','url':f'https://www.douyin.com/video/{i+1}','title':'自有测试','authorization_ref':f'permit-{i}'} for i in range(5)]
        t.status='pending_review'
        for i in range(5):
            for j in range(10):
                db.add(CommentAction(task_id=t.id,account_id=connected,target_id=f'owned-{i}',video_url=t.targets[i]['url'],ordinal=j,body=f'测试候选{i}-{j}，请按实际需求核对规格，私信询价。'))
        db.commit()
    post(client,headers,f'/comment-tasks/{task["id"]}/approve')
    sent=[]
    def adapter(action,payload,key=None):
        sent.append(key)
        return {'ok':True,'status':'sent','comment_id':f'test-{len(sent)}'}
    monkeypatch.setattr(workspace,'request',adapter)
    for _ in range(50):result=post(client,headers,f'/comment-tasks/{task["id"]}/run')
    assert result['status']=='succeeded' and len(set(sent))==50
    post(client,headers,f'/comment-tasks/{task["id"]}/run')
    assert len(sent)==50
    with SessionLocal() as db:
        actions=db.scalars(select(CommentAction).where(CommentAction.task_id==task['id'])).all()
        assert all(sum(a.target_id==f'owned-{i}' for a in actions)==10 for i in range(5))

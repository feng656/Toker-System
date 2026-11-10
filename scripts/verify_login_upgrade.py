"""专用空PG schema证明0003→0004历史数据保留；不删除已有schema或数据。"""
import json
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from app.db import engine
from app import config


def main():
    if config.APP_ENV != 'test' or engine.dialect.name != 'postgresql':
        raise SystemExit('只允许专用PostgreSQL测试环境')
    cfg=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    with engine.begin() as conn:
        if conn.scalar(text('select current_schema()')) != 'jiangguo_login_v3_upgrade':
            raise SystemExit('拒绝操作非指定验证schema')
        if inspect(conn).get_table_names():
            raise SystemExit('只允许空验证schema，不会删除或覆盖已有数据')
        cfg.attributes['connection']=conn
        command.upgrade(cfg,'0003_phase2')
        conn.execute(text("UPDATE platforms SET name='保留原名',enabled=false WHERE code='douyin'"))
        conn.execute(text("UPDATE platforms SET deleted_at=CURRENT_TIMESTAMP WHERE code='xhs'"))
        conn.execute(text("""INSERT INTO workspace_accounts
          (platform_id,label,nickname,avatar_url,status,session_ciphertext,login_attempt_id,qr_object_ref,error,created_at,updated_at,version)
          SELECT id,'历史主号','昵称','','disconnected','fixture-ciphertext','','','',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,3 FROM platforms WHERE code='douyin'"""))
        before=conn.execute(text('select platform_id,label,nickname,status,session_ciphertext,version from workspace_accounts')).one()
        platform_before=conn.execute(text('select id,name,enabled,version from platforms where code=\'douyin\'')).one()
        command.upgrade(cfg,'0004_login_catalog')
        after=conn.execute(text('select platform_id,label,nickname,status,session_ciphertext,version from workspace_accounts')).one()
        assert before==after
        assert platform_before==conn.execute(text('select id,name,enabled,version from platforms where code=\'douyin\'')).one()
        assert conn.scalar(text('select deleted_at is not null from platforms where code=\'xhs\''))
        assert conn.scalar(text('select login_hint from workspace_accounts'))==''
        assert not conn.scalar(text('select generation_enabled from platforms where code=\'taobao\''))
        count=conn.scalar(text('select count(*) from platforms'))
        command.upgrade(cfg,'head')
        assert conn.scalar(text('select count(*) from platforms'))==count
        command.check(cfg)
        print(json.dumps({'account_history_preserved':True,'disabled_and_deleted_preserved':True,
          'catalog_platforms':count,'repeat_upgrade_safe':True,'model_drift':False}))


if __name__=='__main__':main()

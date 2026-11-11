"""在专用验证schema验证带历史数据的0002→0003增量迁移，绝不重置共享库。
仅允许 APP_ENV=test 且search_path为jiangguo_phase2_upgrade_validation。
"""
import json
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from app.db import engine
from app import config


def main():
    if config.APP_ENV!='test' or engine.dialect.name!='postgresql':
        raise SystemExit('只允许PostgreSQL专用测试环境')
    cfg=Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    with engine.begin() as conn:
        if conn.scalar(text('select current_schema()'))!='jiangguo_phase2_upgrade_validation':
            raise SystemExit('拒绝操作非专用验证schema')
        if inspect(conn).get_table_names():
            raise SystemExit('验证schema必须为空；不删除既有数据')
        cfg.attributes['connection']=conn
        command.upgrade(cfg,'0002_backend_closure')
        conn.execute(text("""INSERT INTO contents (id,biz_line,source,title,status,review_note,created_at,updated_at,version)
          VALUES (1,'project','manual','历史发布内容','published','',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1)"""))
        conn.execute(text("""INSERT INTO content_variants (id,content_id,platform,revision,is_current,status,body,cover_text,hashtags,image_prompt,best_time,assets_url,compliance_ok,compliance_hits,quality_score,quality_note,confirm_status,rejection_reason,publish_status,publish_error,publish_result,published_url,published_at,created_at,updated_at,version)
          VALUES(1,1,'douyin',1,true,'published','历史原文','标题','','','','',true,'',90,'','confirmed','','published','','{}','https://www.douyin.com/video/123',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1)"""))
        conn.execute(text("""INSERT INTO metrics (variant_id,stat_date,views,likes,comments,collects,shares,new_fans,dm_inquiries,raw_img_url,source,created_at,updated_at,version)
          VALUES (1,CURRENT_DATE,1000,32,0,0,0,0,0,'','manual',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,1)"""))
        before=conn.execute(text('select body,published_url,status,revision from content_variants where id=1')).one()
        command.upgrade(cfg,'head')
        after=conn.execute(text('select body,published_url,status,revision from content_variants where id=1')).one()
        assert before==after
        assert conn.scalar(text('select sum(views) from metrics'))==1000
        assert conn.scalar(text('select p.code from platforms p join content_variants v on v.platform_id=p.id where v.id=1'))=='douyin'
        command.check(cfg)
        print(json.dumps({'history_preserved':True,'platform_backfilled':True,'metric_views':1000,'model_drift':False}))


if __name__=='__main__':main()

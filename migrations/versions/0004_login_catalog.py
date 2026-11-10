"""主流平台登录目录与账号标识；不扩大默认生成范围、不覆盖停用决策。"""
from datetime import datetime
from alembic import op
import sqlalchemy as sa

revision = '0004_login_catalog'
down_revision = '0003_phase2'
branch_labels = None
depends_on = None

# 历史迁移必须固定数据，不导入未来可能变化的业务目录。
PRESETS = [
    ('douyin', '抖音', 'video', 'https://creator.douyin.com/'),
    ('xhs', '小红书', 'text', 'https://creator.xiaohongshu.com/'),
    ('kuaishou', '快手', 'video', 'https://cp.kuaishou.com/'),
    ('bilibili', '哔哩哔哩', 'video', 'https://member.bilibili.com/'),
    ('shipinhao', '微信视频号', 'video', 'https://channels.weixin.qq.com/'),
    ('gzh', '微信公众号', 'text', 'https://mp.weixin.qq.com/'),
    ('weibo', '微博', 'text', 'https://weibo.com/'),
    ('zhihu', '知乎', 'text', 'https://www.zhihu.com/'),
    ('toutiao', '今日头条', 'text', 'https://mp.toutiao.com/'),
    ('baijiahao', '百家号', 'text', 'https://baijiahao.baidu.com/'),
    ('taobao', '淘宝', 'commerce', 'https://www.taobao.com/'),
    ('jd', '京东', 'commerce', 'https://www.jd.com/'),
    ('pinduoduo', '拼多多', 'commerce', 'https://mms.pinduoduo.com/'),
    ('xianyu', '闲鱼', 'commerce', 'https://www.goofish.com/'),
    ('alibaba1688', '1688', 'commerce', 'https://www.1688.com/'),
]


def upgrade():
    with op.batch_alter_table('platforms') as batch:
        batch.add_column(sa.Column('generation_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column('login_url', sa.String(700), nullable=False, server_default=''))
    with op.batch_alter_table('workspace_accounts') as batch:
        batch.add_column(sa.Column('login_hint', sa.String(200), nullable=False, server_default=''))
        batch.add_column(sa.Column('request_key', sa.String(100), nullable=True))
        batch.create_unique_constraint('uq_workspace_account_request', ['request_key'])
    bind = op.get_bind()
    now = datetime.utcnow()
    for code, name, category, url in PRESETS:
        found = bind.execute(sa.text('SELECT id,login_url FROM platforms WHERE code=:code'), {'code':code}).first()
        if found:
            if not found.login_url:
                bind.execute(sa.text('UPDATE platforms SET login_url=:url WHERE id=:id'), {'url':url, 'id':found.id})
            continue  # 不能覆写已有名称、启停、生成范围或软删除状态。
        bind.execute(sa.text('''INSERT INTO platforms
            (code,name,icon,category,publish_mode,default_time,style_prompt,enabled,generation_enabled,login_url,created_at,updated_at,version)
            VALUES (:code,:name,'',:category,'manual','18:00-20:00','',:enabled,:generation,:url,:now,:now,1)'''),
            {'code':code,'name':name,'category':category,'enabled':True,'generation':False,'url':url,'now':now})
    with op.batch_alter_table('platforms') as batch:
        batch.alter_column('generation_enabled', server_default=None)
        batch.alter_column('login_url', server_default=None)
    with op.batch_alter_table('workspace_accounts') as batch:
        batch.alter_column('login_hint', server_default=None)


def downgrade():
    # 不删除预置平台，避免删掉已关联的账号/内容。新增字段回退前须备份。
    with op.batch_alter_table('workspace_accounts') as batch:
        batch.drop_constraint('uq_workspace_account_request', type_='unique')
        batch.drop_column('request_key')
        batch.drop_column('login_hint')
    with op.batch_alter_table('platforms') as batch:
        batch.drop_column('login_url')
        batch.drop_column('generation_enabled')

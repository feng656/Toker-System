"""幂等初始化。生产管理员密码由环境提供；演示账号只在显式demo模式创建。"""
import os
from sqlalchemy import select
from app import config
from app.auth import hash_password
from app.db import SessionLocal
from app.models import ComplianceRule, Material, Topic, User

RULES = [('forbidden', '底价', '保护渠道价盘'), ('forbidden', '成本价', '保护渠道价盘'),
         ('forbidden', '出厂价', '保护渠道价盘'), ('ad_law', '全国第一', '禁止绝对化表述'),
         ('ad_law', '最便宜', '禁止绝对化表述'), ('required', '私信询价', '统一行动引导')]
TOPICS = [('project', '方案科普', '报告厅LED大屏选型的关键问题', '按使用场景核对参数和交付'),
          ('channel', '工程商痛点', '地州项目现货与技术团队协同', '帮助工程商完成交付，不抢甲方客户')]
MATERIALS = [('公司简介', 'both', '自由光业务简介', '弱电智能化与音视频行业产品和技术服务。'),
             ('服务能力', 'project', '甲方线服务口径', '根据项目场景提供选型、交付与技术支持。'),
             ('服务能力', 'channel', '渠道合作口径', '面向工程商提供现货协同与技术支持，不抢甲方客户。')]
DEMO_PASSWORD = 'Demo-Toker-2026!'


def seed(db, demo=False):
    if not db.scalar(select(User).where(User.username == 'admin')):
        password = DEMO_PASSWORD if demo else os.getenv('BOOTSTRAP_ADMIN_PASSWORD', '')
        if len(password) < 10:
            raise RuntimeError('请设置至少10位BOOTSTRAP_ADMIN_PASSWORD；不自动创建弱默认密码')
        db.add(User(username='admin', name='管理员', role='admin', password_hash=hash_password(password)))
    if demo:
        for username, name, role in [('yunying', '演示运营', 'operator'), ('sales01', '演示销售一', 'sales'), ('sales02', '演示销售二', 'sales')]:
            if not db.scalar(select(User).where(User.username == username)):
                db.add(User(username=username, name=name, role=role, password_hash=hash_password(DEMO_PASSWORD)))
    for kind, pattern, note in RULES:
        if not db.scalar(select(ComplianceRule).where(ComplianceRule.rule_type == kind, ComplianceRule.pattern == pattern)):
            db.add(ComplianceRule(rule_type=kind, pattern=pattern, note=note))
    for line, theme, title, angle in TOPICS:
        if not db.scalar(select(Topic).where(Topic.title == title, Topic.biz_line == line)):
            db.add(Topic(biz_line=line, theme=theme, title=title, angle=angle))
    if demo:
        for category, line, title, content in MATERIALS:
            if not db.scalar(select(Material).where(Material.title == title)):
                db.add(Material(category=category, biz_line=line, title=title, content=content, publicity='public'))
    db.commit()


def main():
    config.validate()
    with SessionLocal() as db:
        seed(db, config.DEMO_MODE)
    print('初始化成功；重复执行不会重复创建账号、规则、选题或演示素材。')
    if config.DEMO_MODE:
        print('仅演示：账号admin/yunying/sales01/sales02，密码见docs/DEPLOYMENT.md。')


if __name__ == '__main__':
    main()

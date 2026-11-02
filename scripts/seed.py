"""种子数据：合规红线 + 首批选题池。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal  # noqa: E402
from app.models import ComplianceRule, Topic  # noqa: E402

RULES = [
    ("forbidden", "底价", "渠道价盘保护：禁止出现底价"),
    ("forbidden", "成本价", "渠道价盘保护"),
    ("forbidden", "出厂价", "渠道价盘保护"),
    ("ad_law", "最便宜", "广告法极限词"),
    ("ad_law", "全国第一", "广告法极限词"),
    ("ad_law", "100%", "广告法极限词"),
    ("ad_law", "最低价", "广告法极限词"),
    ("required", "私信询价", "报价统一口径：引导私信询价"),
]

TOPICS = [
    # 甲方线 project
    ("project", "方案科普", "报告厅LED大屏怎么选：点间距P1.5和P2.0到底差在哪", "以一所学校报告厅改造为场景讲选型逻辑"),
    ("project", "方案科普", "会议室配会议平板还是投影？一张对比表说清", "突出会议平板无线投屏/书写/远程会议优势"),
    ("project", "案例复盘", "一所学校报告厅160万信息化项目是怎么交付的", "用已交付案例讲需求-方案-交付全过程(脱敏)"),
    ("project", "招投标知识", "政企采购LED大屏，招标文件里这5个参数最关键", "帮甲方看懂参数避免踩坑，软性带出京东方总代"),
    ("project", "公司动态", "2000万现货库存是什么概念？带你看我们的仓库", "实力展示，现货=交付速度"),
    # 渠道线 channel
    ("channel", "工程商痛点", "项目急要LED屏现货，厂家排产要45天怎么办", "引出我们2000万现货库存+全省地州配送"),
    ("channel", "工程商痛点", "投标差一个资质，项目眼看要丢", "资质赋能服务介绍，引导私信"),
    ("channel", "工程商痛点", "地州有项目没人施工？带证技术团队可输出", "劳务派遣/技术服务中心卖点"),
    ("channel", "行业观点", "我们不面对甲方——和工程商说清楚这句话的分量", "渠道信任建设，差异化定位"),
    ("channel", "新品到货", "京东方COB新货到仓，地州工程商可预约看样", "总代身份+看样邀约，评论区引导私信"),
]


def main():
    db = SessionLocal()
    if db.query(ComplianceRule).count() == 0:
        for t, p, note in RULES:
            db.add(ComplianceRule(rule_type=t, pattern=p, note=note))
    if db.query(Topic).count() == 0:
        for line, theme, title, angle in TOPICS:
            db.add(Topic(biz_line=line, theme=theme, title=title, angle=angle))
    db.commit()
    print(f"rules={db.query(ComplianceRule).count()} topics={db.query(Topic).count()}")
    db.close()


if __name__ == "__main__":
    main()

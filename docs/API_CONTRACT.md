# 一期后端接口与联调约定

规范前缀 `/api/v1`；机器规范见 `openapi-3.1.json`，运行时 `/openapi.json`。Bearer登录令牌；业务验证错误422，未登录401、无权403、不可见404、状态/唯一键/乐观锁冲突409、依赖不可用503。HTTP错误保留detail并附code；Pydantic字段错误用标准detail数组。

## 通用数据

所有业务表：整数id、created_at/updated_at（UTC）、deleted_at（软删除）、version（乐观锁）。更新接口可带 `expected_version` 防止编辑旧数据；ORM对同时发生的更新再做version条件检查。调用方需传回读到的version，409时刷新，不自动覆盖。列表默认只看未删除记录。

内容变体 `status=draft/blocked/pending/published`；`confirm_status=none/pending/confirmed/rejected`；`is_current=false`为历史。pending表示AI质检合格，confirmed表示人工通过，不能混淆。blocked不能人工放行。`publish_status`是操作进度（none/publishing/filled/submitted/published/failed），不是内容审核状态。

OCR `pending_review/confirmed`。外部推送 `pending/sent/failed/dead`。线索 `new/contacted/opportunity/won/lost/invalid`，不继续使用旧wechat_added。

## 核心调用顺序

| 用途 | 接口 | 请求与要点 |
|---|---|---|
| 登录 | POST /auth/login | username/password，返回token和user |
| 修改密码 | POST /auth/password | old_password/new_password，旧令牌失效 |
| 素材 | GET/POST /materials；PUT/DELETE /materials/{id} | 分类、业务线、公开级别、enabled；删除仅管理员 |
| 选题 | GET/POST /topics；PUT /topics/{id}/status | project/channel；active/used/archived |
| 合规 | GET/POST /rules；DELETE /rules/{id} | forbidden/ad_law命中或required缺失均blocked |
| 每日生成 | POST /generate/daily?scheduled=YYYY-MM-DD | 202返回task_id，重复日期同任务；每条线一个选题×四平台 |
| 任务查询/重试 | GET /tasks/{id}；POST /tasks/{id}/retry | failed可重试，原选题固定；AI逐次日志GET /ai-jobs |
| 内容查询 | GET /contents；GET /contents/{id} | 含全部版本历史及is_current |
| 修改/重新质检 | PUT /variants/{id}；POST /variants/{id}/quality | 文案变更撤销人工通过，须再质检 |
| 人工通过 | POST /variants/{id}/approve | JSON {}或expected_version；不触发外部发布 |
| 驳回 | POST /variants/{id}/reject | 必填reason；返回rejected/new_variant；失败时新版本为空，返回重试入口 |
| 重生成/历史 | POST /variants/{id}/regenerate；GET /variants/{id}/history | 仅有理由的驳回可重试；已有子版本则幂等返回 |
| 今日待办 | GET /todo/today | 仅当前、质检通过、人审confirmed、日期不晚于今天且未回填的版本 |
| 回填真实链接 | POST /variants/{id}/publish | published_url；HTTP(S)公开带路径、不能空/占位/本地/内部编号 |
| 录入日指标 | GET/POST /metrics | variant_id/stat_date及非负计数；同版本同日upsert，必须先发布 |
| 上传截图 | POST /upload/screenshot | multipart kind=metrics/comments、variant_id、f；评论可无版本但须platform |
| OCR确认/重试 | POST /ocr/tasks/{id}/confirm；POST /ocr/tasks/{id}/retry | 见下例；GET /ocr/tasks查询 |
| 新建互动/重新识别 | POST /interactions；POST /interactions/{id}/classify | platform/body/author_id或name；source_key可用于来源幂等 |
| 线索 | GET /leads；GET/PUT /leads/{id} | assignee用销售username；status/follow_notes；详情包含来源和跟进历史 |
| 推送队列 | GET /outbox；POST /outbox/process；POST /outbox/{id}/retry | 未配置/网络/业务错误均可见；dead可人工复活 |
| 看板 | GET /dashboard/funnel、/topics、/trend | trend支持start/end，最多365天区间 |

发布链接验证仅证明格式和公开URL形式，**不声称远端文章真实存在或归属已核验**；不自动请求用户URL，避免SSRF。真实性由运营回填和抽检负责。不同平台提交ID、草稿地址不计数。统计仅status=published、URL非空且有published_at；重复相同链接回填不重复加量。

## OCR人工确认示例

上传返回task.id、image_url（私有对象引用）、fields、confidence、low_confidence_fields、error、status。`GET /ocr/tasks/{id}/image`返回10分钟签名地址。

```json
{
  "data": {
    "stat_date": "2026-11-03",
    "views": 1000,
    "likes": 32,
    "comments": 2,
    "collects": 0,
    "shares": 0,
    "new_fans": 0,
    "dm_inquiries": 0
  },
  "confirmed_fields": ["stat_date", "views", "likes", "comments", "collects", "shares", "new_fans", "dm_inquiries"],
  "expected_version": 1
}
```

每个低置信字段必须同时出现在data和confirmed_fields，缺值不能隐式补0。高置信度也不会自动入库，仍需confirm。评论data格式：`{"comments":[{"author_name":"工程商","body":"项目询价，电话13800138000"}]}`，低置信时confirmed_fields含comments。确认后才建立interactions，再AI识别，失败保留互动和重试入口。

同task相同data重复确认幂等，不同data返回409。截图重传默认按图片摘要、种类和版本去重，也可传Idempotency-Key。

## 去重与推送

30天为最近last_seen窗口。联系方式归一化优先（+86/空白/连字符、邮箱大小写、微信前缀），其次作者标识+平台，最后无联系方式长需求相似度>=0.9。联系方式冲突时不按作者/相似需求误合并。每次来源写lead_sources并标记repeat/repeat_count，不覆盖销售跟进结果。PostgreSQL事务级互斥保证归并的并发串行化；后续大规模运行应改进联系方式索引与候选检索。

高意向/指派/状态变更与outbox同事务写入，worker有界重试+退避，到上限dead。CRM收到Idempotency-Key应幂等处理；企微机器人不支持幂等，崩溃重试存在至少一次语义下的重复通知可能，不能承诺绝对只通知一次。

## 指标口径

metrics是**日增量**，同版本同stat_dateupsert；funnel.views为日增量求和，不要每天上传累计数，否则重复累计。不同平台导出的累计数须由运营换算为当天增量。看板按独立聚合计算，避免多表join倍增。历史版本不进待办，历史已发布数据仍计入历史统计。

## 前端移交点

原web/index.html未修改。前端负责人需：展示blocked/历史、reason输入、新版替换、expected_version回传、只将approve作为人审、OCR低置信逐项确认、推送失败状态和销售用户名选择。`/api`兼容别名仅避免前缀立刻断连，不代表原交互语义完全兼容。

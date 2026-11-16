# M-R4 内容管理优化 · 验收清单

> 版本：v1.0　日期：2026-11-09　责任人：奇迹（前端/测试）
> 环境：本地 FastAPI + SQLite 演示库（`DEMO_MODE=true`，非生产）；浏览器：受管 Chromium（1920×1080）
> 结论：**R4-02/03/04/05/06 前端完成并实测；R4-07 草稿箱被后端接口阻塞，未做死入口；R4-08 验收证据见下。**

## 1. 任务逐项结果

| ID | 任务 | 状态 | 验收结果 | 证据 |
|---|---|---|---|---|
| M-R4-01 | 交互定稿 | 已完成 | 交互口径已落到页面与 `docs/phase2/M-P0-05`；待浆果签字 | `M-P0-05-批量审核与版本对比接口-评审稿.md` |
| M-R4-02 | 多维筛选 | 已完成（前端先行） | 平台/内容状态/版本状态/业务线/排期范围/质量分/合规/确认状态/关键词/仅待办；URL 深链与刷新保留；空态正常 | `evidence/r4/01-contents-filters.png`、`02-filter-deeplink.png` |
| M-R4-03 | 批量审批 | 已完成（兼容模式） | 多选、整批预检、blocked/已确认/合规红线拦截；后端 405 时逐条兼容；逐项结果可见 | `03-batch-precheck-blocked.png`、`04-batch-fallback-success.png` |
| M-R4-04 | 版本对比 | 已完成（只读） | revision 时间线、标题/正文/话题 diff、驳回理由、当前/历史标记；切换当前版本待后端接口 | `05-version-compare.png` |
| M-R4-05 | 待办联动 | 已完成 | `/todo/today` 数量卡；点击按 `scheduled_to` + 仅待办跳转；标签说明「含逾期」 | `01-contents-filters.png` |
| M-R4-06 | 需求转选题 | 已完成 | 线索卡片/详情可转选题；预填主题/标题/角度；来源写入角度；重复线索二次创建需勾选确认；可按「来源线索 #id」检索；详情可显示评论/私信原文 | `06-lead-to-topic-duplicate.png`、`07-topic-source-traceable.png`、`08-lead-interaction-body.png` |
| M-R4-07 | 草稿箱 | **阻塞（未实现）** | 后端无 `POST/PUT /contents`、无 `POST /contents/{id}/submit`；不提供死入口，待浆果接口 | 见本文件 §4 |
| M-R4-08 | R4 验收 | 已完成（除草稿箱） | 3 步内完成筛选→批量；版本对比可用；失败态可复现；草稿箱未验收 | 本清单 + 截图 |

## 2. 实测记录

### 2.1 多维筛选与 URL 同步（M-R4-02）

- 演示库加载 8 个当前版本；无筛选时统计「当前显示 8 个版本；0 个筛选条件」。
- 深链：`#/contents?platform=douyin&variant_status=pending&biz_line=project&keyword=报告厅&scheduled_from=2026-11-01&scheduled_to=2026-11-30&quality_min=85&compliance=ok`
  - 结果：1 个版本（报告厅 LED 大屏 · 抖音 r1），8 个筛选条件回填正确。
  - 刷新页面后 hash 与筛选条件保持不变（app.js 保留非 `tab` 查询参数）。
- 合规值使用 `ok / fail`；`quality_min` 为「≥ 分值」。
- 后端 `GET /contents` 目前只支持 `status/scheduled/limit`，新增维度在前端本地过滤；因此**大数据量下需要浆果补后端过滤参数**，否则前端需拉全量（当前 `limit=500`）。

### 2.2 批量审批预检（M-R4-03）

- 选中「已确认」+「待人工确认」两个版本后点「批量通过」：
  - 整批不写入；弹窗显示「1 个版本未通过预检，整批未提交」；
  - 原因：「人工确认状态为『已确认』」。
- 仅选两个 pending 版本再批量通过：
  - 前端调用 `POST /variants/batch-approve` 得到 **405**，自动进入「逐条兼容」模式；
  - 顺序调用单版本 approve，结果「2 成功 / 0 失败」，列表刷新，待办数由 5 变 7；
  - 弹窗明确提示「后端批量接口未就绪，可能部分写入，请核对列表」。
- 注意：逐条模式不是原子操作；若中途失败，前面已成功的版本不会回滚。这是后端批量接口上线前的已知边界。

### 2.3 版本对比（M-R4-04）

- 视频号 r1→r2：正文 diff `+4 / -1`，r1 显示驳回理由，r2 标记「当前」；
- 标题/话题用字符级 inline diff，正文用并排行级 diff；均在本机计算，不上传正文；
- 「设为当前版本」按后端缺口置灰，并在弹窗底部说明（M-P0-05 未实现切换接口）。

### 2.4 待办联动（M-R4-05）

- 卡片：今日待办 / 明日累计待办 / 待人工确认 / 已拦截 / 平均质量分；
- 后端 `/todo/today` 口径为 `scheduled_date <= target`，因此文案标注「含逾期」，避免把「明日」误读为仅明日；
- 点击卡片设置 `scheduled_to=目标日` + `todoOnly`，列表与数量同源。

### 2.5 需求转选题（M-R4-06）

- 入口：线索卡片「💡 转选题」、线索详情抽屉「用这条需求生成选题」；销售角色不显示（无 `topics` 写权限）。
- 预填：`biz_line=project`、`theme=方案科普`、`title=需求摘要`、`angle=切入建议`。
- 来源追溯：创建时把 `—— 来源线索 #<id>｜<平台>｜<访客>`、原始需求、建议话术写入 `topics.angle` 末尾（后端 `topics` 暂无来源字段），并限制总长 5000。
- 重复提示：打开弹窗并行查询 active/used/archived 选题；若 `angle` 已含同一来源标记，显示红色「该线索已生成过选题」，默认阻止保存，勾选「仍要创建」后才允许。
- 实测：线索 #1 → 创建选题 #3；再次打开显示重复提示；选题池搜索「来源线索 #1」返回 1/3 条。
- 原文展示：线索详情通过 `GET /interactions` 按 `interaction_id` 匹配并显示评论/私信原文、类型和时间，实测见 `08-lead-interaction-body.png`。
- 限制：来源目前是「线索 ID + 平台 + 访客」文本，不是可点击原始评论 URL。`interactions` 没有 `permalink` 字段，无法回链平台原帖；若需要原帖链接，需后端补字段或 `topics` 来源字段。

## 3. 页面与代码落点

| 能力 | 文件 |
|---|---|
| 多维筛选 / 待办 / 批量 / 版本对比 | `web/js/pages/contents.js` |
| 纯前端 diff | `web/js/core/diff.js` |
| 线索转选题 / 销售权限收口 | `web/js/pages/leads.js` |
| 路由保留筛选参数 | `web/js/app.js` |
| R4 样式与响应式 | `web/assets/css/app.css` |

## 4. 草稿箱阻塞说明（M-R4-07）

已核对 `app/api.py`：不存在 `POST /contents`、`PUT /contents/{id}`、`POST /contents/{id}/submit`。现有内容均来自生成任务（`/generate/*`）与版本审核流。为避免运营看到「新建草稿」后必然失败，本期**不放置可点击入口**，只在 `contents.js` 顶部注释与执行报告中登记。

解除条件（浆果）：

1. `POST /contents` 支持 `biz_line/title/topic_id/platforms/scheduled_date`；
2. `PUT /contents/{id}` 支持草稿编辑与 `expected_version`；
3. `POST /contents/{id}/submit` 触发质检/审核，未提交不进 `/todo/today`；
4. 返回内容与版本结构可直接复用现有列表。

## 5. 未覆盖 / 待回归

- 后端真实批量接口上线后，重跑「10 条中 1 条 blocked → 整批不通过」与「10 条合格 → 全部通过」；
- 草稿箱全流程（依赖 §4）；
- 版本「设为当前」切换（依赖 M-P0-05）；
- PostgreSQL/MinIO 环境下的同页回归（当前 SQLite 演示库）；
- 大数据量筛选性能（依赖后端过滤参数）。

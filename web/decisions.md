# 前端工程决策记录（decisions.md）

> 项目：自由光·拓客系统（一期）　范围：把 `web/index.html` 单页原型升级为生产级前端
> 依据：p2p-frontend skill（原型 → 生产级前端）+ 本任务硬约束
> 日期：2026-11-02

本文件是**自主决策审计记录**：每个非显而易见的选择都在这里写清「选了什么 / 为什么 / 备选是什么」。它不阻塞交付，供事后复核与推翻。

---

## §A ⚠️ 自主决策一览（可事后推翻）

| # | 议题 | 选定方案 | 备选 | 理由 | 影响面 |
| --- | --- | --- | --- | --- | --- |
| A-01 | 目标技术栈 | 沿用 Vue3（global build）+ ElementPlus + 原生 fetch，**零构建步骤** | Vite + React + TS + zod + MSW（skill 默认） | 本任务硬约束写明「沿用现有 FastAPI + /api 接口契约与 Vue3 + ElementPlus 单页结构；不更换技术栈」，硬约束优先于 skill 默认 | 整个 `web/` |
| A-02 | 目录形态 | 在 `web/` 内就地模块化（`js/core`、`js/api`、`js/pages`、`assets/css`、`vendor`） | 新建 `frontend/` 目录、保留原型不动（skill 默认） | 任务约束「只改 web/ 与文档」；且原型是唯一的界面基线，就地改造可避免两套页面 | `web/` |
| A-03 | 第三方依赖来源 | Vue / ElementPlus **本地自托管**（`web/vendor/`） | 继续用 unpkg CDN（原型做法） | CDN 不可达会导致整站白屏；自托管后离线也能跑，代价是仓库多约 2.4 MB | `web/vendor/` |
| A-04 | 路由方案 | hash 路由 + 自写角色守卫（`js/app.js`） | 引入 vue-router | 页面数 9 个、无嵌套路由需求；少一个依赖、少一处版本风险 | `js/app.js` |
| A-05 | 请求层 | 自写 `js/core/http.js`（统一前缀、错误归一化、401 广播） | axios + 拦截器 | 原生 fetch 足够；自写可完全控制错误语义（页面需要区分 403 / 网络异常） | `js/core/http.js` |
| A-06 | 数据契约校验 | **不引入** zod / TS 类型；改为「枚举与字段口径集中在 `js/core/format.js`」 | zod strict schema | A-01 的直接后果；前端只读后端既有 JSON，枚举集中管理已能防止口径漂移 | `js/core/format.js` |
| A-07 | Mock / MSW | **不引入** MSW；验收用**独立的桩后端**（照抄 `app/api.py` 语义）放在隔离目录，不进仓库 | MSW 内存 handler | MSW 会让「前端能跑」与「后端契约对不对」脱钩；桩后端保留真实 HTTP 契约，能验证请求路径与字段 | `.pipeline/.../scratch/stub_app.py` |
| A-08 | 四态实现 | 每页统一用 `createAsyncState()`（loading / error / empty / forbidden） | 各页各写 | 9 个页面 × 4 态，手写必然漏；统一封装保证一致性 | `js/core/ui.js` |
| A-09 | 演示账号口令 | 从界面移除，改为只在文档中说明 | 保留在登录页（原型做法） | 明文口令在生产界面属于原型遗留（skill 明确点名要删） | `web/index.html` |
| A-10 | 缺接口的处理 | 占位入口 + 页面内标注 GAP 编号，**不改后端** | 前端 mock 假数据 | 任务约束：不修改 `app/`、不臆造已实现能力 | 全站 |
| A-11 | 「按日期看待办」 | 今天走 `/todo/today`，其他日期用 `/contents?scheduled=` 在前端派生 | 等后端加参数 | 后端无 date 参数（GAP-04）；前端派生口径与后端待办一致（仅 draft/approved、无链接） | `js/pages/todo.js` |
| A-12 | 趋势图 | 前端按 `published_at` 本地聚合最近 7 天，并显式标注来源 | 等 `/dashboard/trend` | 后端没有该接口（GAP-05）；标注避免把本地聚合当成权威口径 | `js/pages/dashboard.js` |
| A-13 | 素材/选题筛选 | 前端精确匹配（分类 / 业务线 / 公开级别 / 关键词 / 启用状态） | 直接用后端 query 参数 | 后端 `biz_line` 过滤是 `in (biz_line, 'both')`，与用户理解的「精确等于」不一致，前端过滤更符合运营直觉 | `js/pages/materials.js`、`topics.js` |
| A-14 | 素材删除权限 | 仅 admin 可删除 | 所有可写角色可删 | 后端 `DELETE /materials/{id}` 只允许 admin；前端与后端保持一致 | `js/pages/materials.js` |
| A-15 | 线索状态枚举 | 以 `app/models.py` 为准（new/contacted/wechat_added/opportunity/won/lost），**不含**《分工》8.1 里的 `invalid` | 严格按《分工》8.1 补 `invalid` | 后端模型没有 `invalid`；前端不造后端不存在的状态（该差异登记在《业务规则与状态口径说明》§3.4） | `js/core/format.js` |
| A-16 | 视觉风格 | 完全沿用原型（深色顶栏 #1f2d3d、170→186px 侧栏、卡片 + ElementPlus） | 按设计系统重绘 | p2p skill 明确「不重设计 UI」；本任务也未要求视觉改版 | `assets/css/app.css` |

## §B 工程结构决策

| 决策 | 内容 | 理由 |
| --- | --- | --- |
| B-01 分层 | `js/core`（运行时、HTTP、状态、格式化、UI 原语）→ `js/api`（按域的服务层）→ `js/pages`（页面组件）→ `js/app.js`（壳与路由） | 页面不直接 `fetch`，所有请求都走服务层，后端改契约时改动面可控 |
| B-02 服务层按域拆分 | `auth` / `library`（素材·选题·红线）/ `content`（内容·变体·待办·生成）/ `business`（线索·互动·指标·看板）/ `platform`（账号·浏览器·截图） | 与后端 `app/api.py` 的分段一致，便于对照阅读 |
| B-03 错误归一化 | `ApiError(status, detail, url)`，页面按 `forbidden / unauthorized / offline` 分支渲染 | 四态的前提是错误可分类 |
| B-04 401 广播 | HTTP 层统一清 token 并广播 `tk:auth-expired`，`app.js` 订阅后回登录页 | 避免每个页面各写一遍登出逻辑 |
| B-05 全局计数 | 待办条数由 `store.counters` 维护，菜单红点每 60 秒刷新一次 | 菜单红点是运营最常用的导航信号 |
| B-06 依赖加载顺序 | `vendor/*.js` 以传统 script 加载，`js/*.js` 以 ES module 加载 | ES module 默认 defer，会在传统 script 之后执行，保证 `window.Vue` / `window.ElementPlus` 就绪 |
| B-07 状态文案集中 | 所有枚举 → 中文映射集中在 `js/core/format.js` | 满足《分工》8.2「后端不把展示文本当作业务状态」 |

## §C 明确不做的事（及原因）

| 不做 | 原因 |
| --- | --- |
| 不修改 `app/` 任何文件 | 任务约束：后端归浆果 |
| 不引入 TypeScript / Vite / zod / MSW / vue-router / axios | A-01（不更换技术栈） |
| 不做「设计系统绑定 / 视觉重绘」 | 任务未要求；p2p skill 明确不重设计 UI |
| 不新建正式的 E2E 测试基建（`pios test run start` 等） | 任务未要求正式回归登记；自测走查脚本放在隔离目录，不进仓库 |
| 不为后端缺口写假数据 | 任务约束「不臆造后端已实现能力」 |
| 不做后端 `/api/v1` 迁移 | 属后端范围（记为 GAP-01）；前端前缀集中在 `js/core/http.js` 一个常量 |

## §D 已知取舍

| 取舍 | 影响 | 何时该改 |
| --- | --- | --- |
| 前端本地聚合趋势图 | 数据量大时需要拉全量内容明细 | 后端提供 `/dashboard/trend` 后替换（`js/pages/dashboard.js`） |
| 待办非今日由前端派生 | 每次切换日期会拉取内容列表 | 后端支持 `?date=` 后替换（`js/pages/todo.js`） |
| 线索联系方式去重只做提示 | 仍需人工合并 | 后端实现 GAP-08 后替换（`js/pages/dashboard.js` 的 `duplicateContacts`） |
| 联系方式提取依赖大模型 | 无 Key 时打标结果质量下降 | 属后端 `app/classifier.py` 范畴 |
| 移动端为响应式收敛（侧栏折叠为图标） | 未做专门的移动端工作台 | 分工 6 章提到「看板和移动端适配」由我方负责，一期为桌面优先 |

---

## §E P0 工作台（拖动投放与平台通道）追加决策

> 阶段：PL-3689 / stage-20186　日期：2026-11-02　依据：《06-系统框架V0.1》2.1–2.5、《03-合规词-资质-免责声明确认表》《01-业务口径确认表》

| # | 议题 | 选定方案 | 备选 | 理由 | 影响面 |
| --- | --- | --- | --- | --- | --- |
| E-01 | 平台通道规格落点 | 新增 `js/core/platforms.js` 集中四通道字段、文案格式、免责声明、行动引导、版本→草稿填充 | 写进 `format.js` | `format.js` 职责是状态枚举与通用格式化，通道规格是新的业务维度，独立文件更易维护；不改 A-06 决定 | `web/js/core/platforms.js` |
| E-02 | tab 实现方式 | 自绘 tab 条（`.wk-tab`）+ 面板 | ElementPlus `el-tabs` | 需求要求「拖到 tab 松手」，自绘 tab 才能在 tab 本身挂 dragover/drop 与高亮；`el-tab-pane` 不便在标签上挂事件 | `web/js/pages/work.js`、`app.css` |
| E-03 | composer 状态粒度 | 每个通道一份独立草稿（切换 tab 不丢内容） | 全局单份 | 运营会在四个平台之间来回微调，共用一份会互相覆盖 | `work.js` |
| E-04 | 免责声明版本 | 四平台统一用 4.1 公众号/长图文版 | 按平台各选一版 | 《03》五-3 人工确认「4.1，统一附」；不自行按平台改口径 | `platforms.js` |
| E-05 | 闲鱼价格 | 只作为独立字段，不进复制文案；成色进文案 | 价格直接写进文案 | 《06》0 节价格口径「不出现价格数字」+《01》六 | `platforms.js` |
| E-06 | 行动引导 | 分平台写死在通道规格里（抖音私信 / 小红书评论私信 / 公众号留言加微信 / 闲鱼站内信） | 让运营手填 | 《01》三-4 已确认「分平台」 | `platforms.js` |
| E-07 | 「标记已发」 | 必须粘贴发布链接，校验通过才调 `POST /variants/{id}/publish` | 允许只标记状态不回填链接 | 延续 PL-3688 硬门槛「空链接不计入发布量」，不能让前端做出无链接的假「已发布」 | `work.js` |
| E-08 | 跨平台投放 | 内容版本平台与目标通道不一致时弹确认，确认后按目标平台重排字段 | 直接重排不提示 | 《06》2.2 第 4 条，避免错投 | `work.js` |
| E-09 | 媒体字段 | 只展示「配图建议 + 素材状态 + 去素材库补充」，不伪造图片链接 | 前端拼占位图 | 后端 `_variant_dict` 不返回 `assets_url`，前端无真实媒体地址可给 | `platforms.js`、`work.js` |
| E-10 | 素材覆盖统计 | 独立调 `/materials` 统计可公开/需脱敏/仅内部，失败只提示不阻塞 | 复用内容池推导 | 覆盖口径是素材库自己的口径，不能从内容推导；失败不阻塞是《06》2.5「不阻塞工作台」 | `work.js` |
| E-11 | 「先用文字版」 | 全局开关：清空各通道媒体字段并在媒体位标注「纯文字版」，其余流程照常 | 只做提示文案 | 《06》2.5 要求的两个入口之一，必须真能继续干活 | `work.js` |
| E-12 | 真实发布入口 | 置灰按钮「发布（API）· P1 接入」+ hover 说明 | 隐藏按钮 / 做成可点 | 任务明确要求「置灰并标注 P1 接入」，隐藏会让人以为漏做 | `work.js` |
| E-13 | 视觉 | 沿用现有深色顶栏 + 卡片 + ElementPlus，仅新增工作台样式段 | 按设计系统重绘 | 延续 A-16；本阶段任务未要求视觉改版，且项目未绑定设计系统 | `assets/css/app.css` |
| E-14 | 自测方式 | Playwright 夹具跑在照抄 `app/api.py` 语义的桩后端上（隔离目录，不进仓库） | 正式 E2E 基建 / 等真实环境 | 任务未要求正式回归登记（范围纪律）；沙箱无 PostgreSQL 与大模型 Key | `.pipeline/PL-3689/stage-20186/scratch/` |

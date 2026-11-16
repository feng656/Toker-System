# M-P0-03 前端 `/api/v1` 迁移清单

> 版本：v1.0　日期：2026-11-09　状态：前端已切换，待联调
> 依据：`docs/API_CONTRACT.md`（规范化前缀 `/api/v1`）、`app/main.py:38-40`（同时挂载 `/api/v1` 与 `/api`）
> 代码：`web/js/core/http.js`

## 1. 切换方式

- 默认前缀改为 `/api/v1`。
- 过渡开关（二选一，按优先级）：
  1. `localStorage.setItem('tk_api_prefix', '/api')` —— 单浏览器回退旧前缀；
  2. `window.__TK_API_PREFIX__ = '/api'` —— 部署级临时回退。
- 只允许 `/api/v1` 与 `/api` 两个值；其他值忽略并回落 `/api/v1`。
- 旧 `/api` 仅作兜底，不作为新功能开发目标；联调通过后删除开关。

## 2. 已迁移调用

| 模块 | 方法 | 原路径 | v1 路径 | 语义变化 / 前端处理 |
|---|---|---|---|---|
| app | 登录 | `window.fetch('/api/auth/login')` | `POST /api/v1/auth/login` | 走 `authApi.login`；统一 401/429 文案 |
| app | 会话恢复 | `window.fetch('/api/auth/me')` | `GET /api/v1/auth/me` | 走 `authApi.me`；401 自动清会话 |
| auth | 登录 | `/auth/login` | `/auth/login` | 无变化 |
| auth | 当前用户 | `/auth/me` | `/auth/me` | 无变化 |
| auth | 用户列表/创建 | `/users` | `/users` | 无变化 |
| content | 内容列表 | `/contents` | `/contents` | 新增筛选参数见 M-R4-02；后端未支持时前端本地过滤 |
| content | 内容级审核 | `/contents/{id}/review` | 同路径 | **降级为兼容入口**；新交互改用变体级 approve/reject |
| content | 变体列表/历史 | - | `/variants/{vid}/history` | 新增前端调用，用于版本对比 |
| content | 变体通过 | `/variants/{vid}/confirm` | `/variants/{vid}/approve` | `confirm` 仅保留为后端兼容别名，前端不再调用 |
| content | 变体驳回 | `/variants/{vid}/confirm-reject` | `/variants/{vid}/reject` | 请求体 `{reason, expected_version}`；理由必填 |
| content | 变体重生成 | - | `/variants/{vid}/regenerate` | 仅驳回后可重试；前端按需调用 |
| content | 修改变体 | `/variants/{id}` | `/variants/{id}` | 必须带 `expected_version`，409 提示刷新 |
| content | 回填发布 | `/variants/{id}/publish` | 同路径 | 带 `expected_version`；前端先校验 URL |
| content | 待确认 | `/confirm/pending` | 同路径 | 只读；后续可改用 `/variants?confirm_status=pending` |
| content | 今日待办 | `/todo/today` | `/todo/today?scheduled=` | 支持日期参数；前端今日/明日计数 |
| platform | 账号状态 | `/accounts/status` | 同路径 | 后续切到 `/platforms/{id}/accounts`（M-P0-04） |
| platform | 保存账号 | `/accounts` | 同路径 | 单账号模型；多账号接口待 M-P0-04 |
| platform | 浏览器打开/截图 | `/browser/{platform}/open`、`/screenshot` | 同路径 | 后续改为 `account_id` 维度 |
| library | 素材/选题/规则 | `/materials`、`/topics`、`/rules` | 同路径 | 无变化 |
| business | 线索/互动/指标/看板 | `/leads`、`/interactions`、`/metrics`、`/dashboard/*` | 同路径 | 无变化 |

## 3. 错误语义迁移

| 场景 | v1 约定 | 前端处理 |
|---|---|---|
| 乐观锁冲突 | `409` + `detail`，可带 `expected_version` | 提示「数据已被他人更新」，刷新后重试，不自动覆盖 |
| blocked 版本 | `409` / 变体 `status=blocked` | 批量审批整批阻止，列出命中的 variant_id 与原因 |
| 参数校验 | `422` + `detail[]` | 逐字段展示；不显示原始 JSON |
| 限流 | `429` + `retry_after` | 倒计时；禁用提交；有挑战则展示挑战 |
| 依赖不可用 | `503` + `code` | 提示稍后重试；不判定为业务失败 |
| 旧端点 | `404/405` | 提示「接口未就绪」；不静默改用旧语义 |

## 4. 验收清单

- [ ] 所有页面请求 URL 以 `/api/v1` 开头（DevTools Network 抽查 9 页）。
- [ ] 登录、会话恢复不再出现裸 `window.fetch('/api/...')`。
- [ ] 401 清会话并回登录页；403 显示无权限；429 显示倒计时；409 显示刷新提示。
- [ ] 变体审核调用 `/approve`、`/reject`，不再调用 `/confirm`、`/confirm-reject`。
- [ ] 修改/发布变体带 `expected_version`，409 可复现。
- [ ] 旧 `/api` 回退开关可用，切换后页面功能不报错。
- [ ] `docs/API_CONTRACT.md` 中每个前端实际调用都有对应条目。

## 5. 待浆果确认

- `POST /variants/batch-approve`、`/batch-reject` 的最终路径与请求体（见 M-P0-05）。
- `GET /contents` 新过滤参数的上线时间；未上线期间前端本地过滤只覆盖已加载的 100 条。
- `POST /auth/register`、`GET /auth/register/config` 的开关与返回结构（见 M-P0-06 / R10）。
- 旧 `/api` 兼容别名计划下线时间；下线前提前一个迭代通知。

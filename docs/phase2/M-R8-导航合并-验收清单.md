# M-R8 左侧模块合并 · 验收清单

> 版本：v1.0　日期：2026-11-09　责任人：奇迹（前端/测试）
> 环境：本地 FastAPI + SQLite 演示库；受管 Chromium 1920×1080
> 结论：**R8-01/02/03 前端完成；R8-04 除移动端真机外完成，9 页 SPA 切换 0 控制台错误。**

## 1. 信息架构

| 一级菜单 | 二级 tab | 旧 hash | 可访问角色 |
|---|---|---|---|
| 工作台 | 投放工作台 / 今日待办 | `#/todo` → `#/work?tab=todo` | admin / operator |
| 内容 | 内容管理 / 选题池 | `#/topics` → `#/contents?tab=topics` | admin / operator |
| 素材 | 素材库 | — | admin / operator |
| 线索 | 线索看板 | — | admin / operator / sales |
| 数据 | 数据看板 | — | admin / operator / sales（只读） |
| 设置 | 设置 / 帮助 | `#/help` → `#/settings?tab=help` | 全部角色 |

- 面包屑：一级菜单 / 当前 tab；无 tab 页面只显示一级标题。
- 默认落地页：admin/operator → `work`；sales → `leads`。
- 菜单徽标：仅工作台显示待办数，数据来自 `/todo/today`，60 秒刷新一次。

## 2. 实测结果

| 检查项 | 结果 | 证据 |
|---|---|---|
| 一级菜单 6 个 | 通过：工作台/内容/素材/线索/数据/设置 | `evidence/r8/02-nav-6-menus.png` |
| 9 页可达 | 通过：work、todo、contents、topics、materials、leads、dashboard、settings、help | 本文件 §3 |
| SPA 切换控制台错误 | 0（9 页连续切换，`window.onerror` / `unhandledrejection` / `console.error` 收集均为 0） | 本文件 §3 |
| 旧 hash 重定向 | 通过：`#/todo`→`#/work?tab=todo`；`#/topics`→`#/contents?tab=topics`；`#/help`→`#/settings?tab=help` | `01-legacy-todo-redirect.png` |
| 未知页面 | 通过：显示「页面不存在」，不白屏 | 实测 |
| sales 菜单 | 通过：仅线索/数据/设置 | `03-sales-leads-menu.png` |
| sales 越权访问 | 通过：访问 `#/contents` 显示「没有访问权限」，列出可访问页面；不渲染业务内容 | `04-sales-route-guard.png` |
| 销售线索按钮收口 | 已修：销售不显示「录入评论/私信」「转选题」「推送企微」，指派输入框禁用 | 代码 + 页面 |
| 移动端 | **未做真机/视口验收**；CSS 断点 1100/860/560 已保留（菜单收窄、待办卡 3→2→1 列、版本对比单列） | 待补 |

> 销售角色控制说明：`POST /interactions`、`POST /leads/{id}/push` 在后端要求 admin/operator；此前页面仍展示按钮会得到 403。本次按 `canWriteContent` 收口，避免「看得到点不动」。

## 3. 9 页逐页结果

| # | 路由 | 页面标题 | 控制台错误 |
|---|---|---|---|
| 1 | `#/work` | 今日内容工作台 | 0 |
| 2 | `#/work?tab=todo` | 今日待办（0 条待处理） | 0 |
| 3 | `#/contents` | 内容管理 | 0 |
| 4 | `#/contents?tab=topics` | 选题池 | 0 |
| 5 | `#/materials` | 素材库 | 0 |
| 6 | `#/leads` | 线索看板 | 0 |
| 7 | `#/dashboard` | 数据看板 | 0 |
| 8 | `#/settings` | 设置 | 0 |
| 9 | `#/settings?tab=help` | 帮助 | 0 |

## 4. 代码落点

- `web/js/core/store.js`：`MENUS`、`PAGE_TABS`、`LEGACY_ROUTES`、`PAGE_ROLES`、`tabsFor`、`canAccess`、`defaultRoute`。
- `web/js/app.js`：hash 解析、旧路由映射、角色守卫、tab 规范化、保留非 tab 查询参数、面包屑标题。
- `web/index.html`：6 个一级菜单、二级 tab、面包屑、登录/注册壳。
- `web/js/pages/leads.js`：销售角色按钮/指派收口。

## 5. 遗留

- 移动端需在真实浏览器视口（375/768）补截图；当前环境无 viewport 切换能力。
- `#/materials`、`#/leads`、`#/dashboard` 无二级 tab，面包屑只显示一级，符合设计。
- 后端 `GET /todo/today` 只支持今天；工作台「今日待办」与内容页「明日累计待办」文案已显式标注「含逾期」，避免口径误解。

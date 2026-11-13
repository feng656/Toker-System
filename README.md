# 自由光 · 拓客系统

> **平台账号登录增量 v3**：工作台支持15个常见平台、填写账号后请求二维码、自定义平台保存、扫码状态有界查询及过期重取。先升级数据库到 `0004_login_catalog`，详见[使用/升级/验收说明](docs/PLATFORM_LOGIN_V3.md)。后端94项×两套环境及轮询6项通过；真实扫码仍需要已授权平台适配服务，预置平台不等于已接通。该增量基于二期前端PR #4，未改动其源分支。

> **二期后端联调版**：动态平台、批量审核、素材/视频任务、工作空间、授权互动和登录安全已增量实现。先看[二期升级指南](docs/PHASE2_DEPLOYMENT.md)、[接口契约](docs/PHASE2_API_CONTRACT.md)、[适配协议](docs/PHASE2_ADAPTERS.md)和[73项测试报告](docs/PHASE2_TEST_REPORT.md)。真实平台服务与账号、AI key、Gitee授权仍待联调，不宣称已可生产上线。

AI 内容工厂 + 半自动多平台发布 + 评论线索挖掘。前端为**零构建 Vue 3（全局构建）+ ElementPlus** 单页应用，后端为 FastAPI + SQLAlchemy 2 + PostgreSQL/MinIO。

> **协作入口**：主仓 [github.com/feng656/Toker-System](https://github.com/feng656/Toker-System)。
> 本批前端工作在 `feat/frontend-jiangzhuofeng` 分支；后端在 `feat/jiangguo-backend-closure`。合并前必须经过 PR 互审，不直接 push `main`。
> Gitee 镜像地址待资源负责人提供（M-R5-01），当前**没有可登记的公开镜像链接**，请勿把未验证的地址写进文档。

## 快速启动

完整环境变量、迁移、生产/Compose 与测试说明见 **[后端部署说明](docs/DEPLOYMENT.md)**。最简本地演示：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env          # 填写 DATABASE_URL / JWT_SECRET / MINIO_*
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.seed
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8300
# 浏览器打开 http://127.0.0.1:8300
```

- 管理员密码来自 `BOOTSTRAP_ADMIN_PASSWORD`；仅测试库设置 `DEMO_MODE=true` 后运行种子，演示账号为 `admin / yunying / sales01 / sales02`，演示密码见 `docs/DEPLOYMENT.md`，生产禁止使用。
- 前端不需要 `npm install` 或打包，`web/` 由 FastAPI 直接托管；修改 JS/CSS 后刷新页面即可。
- `/api/v1/health` 检查数据库；`/docs` 与 `docs/openapi-3.1.json` 是接口联调入口。

## 目录

- `app/`：FastAPI 后端（认证、内容/版本、审核、OCR、线索、发布、调度、通知）
- `web/index.html`：应用壳；`web/js/core`（HTTP/会话/状态/格式化）→ `web/js/api`（接口封装）→ `web/js/pages`（9 个页面）
- `docs/phase2/`：二期 Phase 0 口径/模型/接口评审稿、Phase 1 验收清单与执行报告
- `docs/DEPLOYMENT.md`、`docs/API_CONTRACT.md`、`docs/COLLABORATION.md`：部署、接口契约、双人协作规则
- `scripts/`：种子、PPT 素材导入、端到端演示

## 当前状态（2026-11-11）

- 后端 `v2.0.0` 已合并二期后端（PR #3）与平台登录增强（PR #5），迁移到 `0004_login_catalog`；前端已合并二期前端（PR #4）。
- 内容管理同时保留「内容包（按选题）」与「版本筛选与批量审核（二期）」两个视图；平台 AI 文案与视频生成入口保留在设置页和版本编辑区。
- 真实平台账号、Gitee 镜像/多网络验收、评论/私信的真实平台适配仍依赖用户提供资源，未配置时明确失败而不伪造成功。

## 外部依赖

- AI 能力已接入本平台（πOS）：文案填 `PIOS_MODEL_KEY`（`pios model key` 签发）即走平台模型网关，默认 `moonshotai/kimi-k3.1-pro` 主模型 + `qwen/qwen3.8-2.4t-a95b` 备用；视频填 `PIOS_API_URL` + `PIOS_TOKEN`，走平台 `/agent-api/video/*`（默认 `MiniMax-H3` 2K，上游 502 时自动降级到 `doubao-seedance-2-0-mini-260615` 1080P 重试一次）。未配置时任务显式失败或标记演示，不回退为假成功。
- `WECOM_WEBHOOK`、CRM：线索推送进入 outbox，失败可重试；未配置时页面明确提示。
- 素材：真实公司资料、已授权案例图、平台发布链接由业务负责人提供；演示素材标记为演示。

# 自由光 · 拓客系统

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

## 当前状态（2026-11-09）

- 前端 Phase 1 已完成 R4 内容管理、R8 导航合并、R10 登录安全、R5 README 复核的可做部分；详见 [Phase 1 执行报告](docs/phase2/01-Phase1-总览与出口检查.md)。
- 批量审核/版本切换、草稿箱、登录限流/验证码、平台动态配置、沙盒、评论/私信、AI Provider 等后端接口仍待浆果实现；前端不以假数据冒充联调，缺口与阻塞见 [二期接口缺口与待确认清单](docs/phase2/02-接口缺口与待确认清单.md)。
- R5 的 Gitee 镜像/多网络验收、R2/R6/R7 的真实平台账号仍依赖用户提供资源。

## 外部依赖

- `LLM_PROVIDERS` / 文案与视频 API Key：配置后真实生成，未配置时任务显式失败或标记演示，不回退为假成功。
- `WECOM_WEBHOOK`、CRM：线索推送进入 outbox，失败可重试；未配置时页面明确提示。
- 素材：真实公司资料、已授权案例图、平台发布链接由业务负责人提供；演示素材标记为演示。

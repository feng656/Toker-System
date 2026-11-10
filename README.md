# 自由光 · 拓客系统 MVP

> **平台账号登录增量 v3**：工作台支持15个常见平台、填写账号后请求二维码、自定义平台保存、扫码状态有界查询及过期重取。先升级数据库到 `0004_login_catalog`，详见[使用/升级/验收说明](docs/PLATFORM_LOGIN_V3.md)。后端94项×两套环境及轮询6项通过；真实扫码仍需要已授权平台适配服务，预置平台不等于已接通。该增量基于二期前端PR #4，未改动其源分支。

> **二期后端联调版**：动态平台、批量审核、素材/视频任务、工作空间、授权互动和登录安全已增量实现。先看[二期升级指南](docs/PHASE2_DEPLOYMENT.md)、[接口契约](docs/PHASE2_API_CONTRACT.md)、[适配协议](docs/PHASE2_ADAPTERS.md)和[73项测试报告](docs/PHASE2_TEST_REPORT.md)。真实平台服务与账号、AI key、Gitee授权仍待联调，不宣称已可生产上线。

> 后端协作分支已补齐迁移、权限、审核、OCR确认与推送队列。**当前启动方式、账号及外部依赖以 [后端部署说明](docs/DEPLOYMENT.md) 为准**；以下为原始MVP说明，原弱默认密码和stub行为已停用。前端页面原样保留，新增交互由前端负责人按 [接口约定](docs/API_CONTRACT.md) 联调。

AI 内容工厂 + 半自动发布 + 评论线索挖掘。

## 启动

```bash
cd tuoke
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8300
# 初始化与登录凭据按 docs/DEPLOYMENT.md 配置；禁止使用历史弱默认密码
```

## 初始化

```bash
.venv/bin/python scripts/import_pptx.py "../拓客/2025-11-19自由光公司介绍-项目.pptx" "../拓客/2025-11-19自由光公司介绍-渠道.pptx"
.venv/bin/python scripts/seed.py
```

## 结构

- `app/` FastAPI 后端（config/db/models/auth/api/generator/classifier/scheduler/report/notify/storage/llm）
- `web/index.html` 单页管理台（Vue3+ElementPlus，CDN 引入）
- `scripts/` 数据初始化
- `.env` 连接配置（PG/Redis/MinIO/LLM key/企微 webhook 待填）

## 待接入（二期）
- LLM_API_KEY：配 deepseek/通义等 key 后文案生成与评论打标即真实启用（当前 stub 占位）
- 截图 OCR 识别（upload/screenshot 已存图，解析待做）
- 公众号草稿箱 API（需认证服务号 AppID/Secret）
- WECOM_WEBHOOK：企微群机器人地址，高意向线索自动推送

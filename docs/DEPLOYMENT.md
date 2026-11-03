# 后端部署与初始化（浆果交付）

## 1. 边界与配置

Python 3.11、PostgreSQL 15+、私有 MinIO/S3兼容对象存储。业务数据不可落临时SQLite文件；SQLite只用于内存隔离测试。平台环境先申请/使用托管资源，不在开发容器自启数据库。

先复制 `.env.example` 为 `.env`，填写 `DATABASE_URL`、随机 `JWT_SECRET`（至少32字符）、`MINIO_*`。连接地址以资源当前endpoint为准。不要提交 `.env`、登录态、API密钥。UTC时间写库，调度时区为Asia/Shanghai。

## 2. Python启动（Windows/Linux）

在仓库根目录执行，Windows将 `.venv/bin/` 替换为 `.venv/Scripts/`：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/alembic upgrade head
# 生产初始化前在环境中设置 BOOTSTRAP_ADMIN_PASSWORD（至少10字符）
.venv/bin/python -m scripts.seed
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8300
# 另一个终端；仅一个worker进程，API进程不启动scheduler
.venv/bin/python -m app.worker
```

API启动不会自动建表或创建弱默认密码；迁移未达head会拒绝启动。`/api/v1/health` 检查数据库。`/docs` 为接口文档，静态 `docs/openapi-3.1.json` 可导入联调工具。

### OCR运行依赖

Tesseract本地适配需安装 `tesseract-ocr`、中文简体和英文语言包并加入PATH。Debian/Ubuntu包名：`tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-eng`。也可设置 `OCR_BACKEND=http` 接入受信的OCR服务，契约见 `ADAPTERS.md`。识别失败进入待审并记录错误，可重新识别或逐项人工校录，不会静默写入指标。

## 3. Compose部署

```bash
docker compose build
docker compose up -d api worker
docker compose --profile tools run --rm seed
```

Compose包含一次性迁移、API、单独worker和手动seed，连接外部数据库/对象存储，不包含持久化服务容器。服务默认仅映射127.0.0.1:8300，生产需由反向代理配置HTTPS及访问边界。容器只读，临时OCR文件写/tmp。镜像包含Tesseract及中英文语言包。生产部署到平台应使用平台部署通道；本交付不宣称已上线。

`apscheduler_jobs`由迁移创建，不能让多个APScheduler实例共享该jobstore。API可多进程，worker严格一个副本；内容任务有事务级互斥及日期唯一键，outbox同事件有唯一键。

## 4. 演示账号与种子数据

仅测试库中显式设置：

```dotenv
APP_ENV=development
DEMO_MODE=true
```

再运行 `python -m scripts.seed`。账号 `admin`（管理员）、`yunying`（运营）、`sales01`/`sales02`（销售），演示密码统一为 `Demo-Toker-2026!`。生成结果及AI日志明确标记演示，不能当成真实外部模型验收。生产禁止 `DEMO_MODE=true`，生产管理员由 `BOOTSTRAP_ADMIN_PASSWORD`创建，其他账号由管理员创建。

种子包含3条非真实业务素材、甲方线/渠道线选题、禁用/广告法/必需口径规则；重复运行不重复创建。真实公司资质、库存、业绩等事实由业务负责人确认后替换。

修改密码：登录后 `POST /api/v1/auth/password`，提交 `old_password` 和 `new_password`；旧令牌随即全部失效。销售只能看被指派给自己的线索，不能改派，不能访问素材、AI日志、全量互动、指标和管理看板。

## 5. 测试与九步演示

```bash
python -m pip install -r requirements-dev.txt
pytest -q
python -m scripts.e2e_demo --mode isolated --out reports/e2e-isolated.json
# 使用已配置的专用开发数据库/对象存储，走真实持久化，但AI/推送仍为显式演示替身
python -m scripts.e2e_demo --mode configured --out reports/e2e-configured.json
```

真库回归须使用专用测试数据库或专用schema；`ALLOW_TEST_DATABASE_RESET=yes`才允许测试重置该schema，**禁止指向生产或共享业务schema**。`DATABASE_URL`可加 `?options=-csearch_path%3Dyour_test_schema`。

## 6. 旧源码与接口兼容

`/api`保留为迁移期别名，响应带Deprecation，规范路径统一`/api/v1`。`confirm`现在只做人审，不自动发布；`confirm-reject`必须传reason。前端原文件未修改，旧按钮可能需由前端负责人按新契约调整，不能把原页面仍可打开说成新流程已完成前端联调。

原 `部署说明.md`、`操作说明.md`为历史基线，不再是本分支部署依据。

## 7. 已知未验收事项

- 生产AI密钥、实际企微机器人与CRM接收端、平台账号素材/权限未提供，真实外部投递不在本次通过结论内。
- 官方发布、受控浏览器填稿为默认关闭的实验适配，不作为一期发布前提。提交ID、填稿成功都不计发布量。
- 本次环境没有Docker Compose运行插件，Compose仅做结构/命令静态检查，未执行镜像构建或容器启动。
- 已有旧数据库升级：本次迁移针对空库。旧数据需先备份、导出和字段/状态映射评审，禁止对现有库直接stamp或强行覆盖；未声称完成旧库在线迁移。

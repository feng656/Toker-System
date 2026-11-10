# MVP 平台账号登录增量 v3

## 可以直接使用的功能

入口：**工作台 → 平台账号 → 添加账号**。

1. 可搜索的 15 个常见平台：抖音、小红书、快手、哔哩哔哩、微信视频号、微信公众号、微博、知乎、今日头条、百家号、淘宝、京东、拼多多、闲鱼、1688。
2. 选择平台，填写账号标识（手机号、用户名或账号名称），可另填备注；点击“保存账号并获取二维码”。创建成功即持久化，扫码服务失败不丢账号、不自动创建第二条。
3. 目录没有目标平台时，点击“找不到平台？手动添加并保存”。填写平台名称、可选官方入口/适配器约定标识，保存后自动选中；下次进入及其他运营人员可以复用。
4. 扫码界面请求平台授权图片，主动查询登录状态，显示倒计时、成功、过期与依赖错误；关闭或切换账号后旧响应不能覆盖当前弹窗。
5. 已停用平台保留灰色状态，不因本次升级被擅自开启。管理员可在“设置 → 平台管理”启用。旧的小红书兼容记录默认停用，也遵循此规则。

**真实扫码依赖尚未提供，当前交付不是“15个平台均已真实接通”。** 保存平台和账号是可用功能；获取有效二维码必须由已授权的真实平台服务支持。账号文本本身不能生成有效凭证，不能保证扫码人就是填写的账号，最终以平台实际授权昵称/会话为准。自定义网址仅是人工打开链接，不交给适配器任意导航。

## 协作与范围

- 本增量基于 PR #4 的前端提交 `b1794b6db8ceac07ce44a5ddbe1d1ad0b12b49fc`。该页面不在当时的 main 中；main 已合并二期后端 PR #3，SHA 为 `ca403bf186d0f115af46fd1d260941b67bb980a7`。
- 独立分支 `feat/platform-login-jiangguo`，不修改 main 或 PR #4 的源分支。建议以 `feat/phase2-frontend` 为 PR 比较基线，仅审阅本模块增量；先协调原 PR 合入顺序，不能重复覆盖前端工作。
- 前端改动限于账号组件、调用、工作台接线、平台设置新增字段及局部样式。未重构内容管理、线索、素材等页面。
- 账号目录与每日内容生成范围分开：新增登录预置/自定义平台默认 `generation_enabled=false`，不会把每日2×4内容突然变成2×15。设置里显式启用“内容生成”后才加入。
- 朋友圈没有独立网页扫码入口，仍保留原内容平台，不列入扫码目录。

## 数据库升级

先备份数据库，停写并停 worker，然后在正确的业务 PostgreSQL 环境执行：

```bash
python -m alembic upgrade head
python -m alembic current
# 预期：0004_login_catalog
```

`0004_login_catalog` 为增量迁移：
- `platforms.generation_enabled`、`platforms.login_url`；历史行生成范围保持原有启用逻辑。
- `workspace_accounts.login_hint`、可空唯一 `request_key`；旧账号、会话、状态和版本不改。
- 补齐缺失的平台；不覆盖已有名字、启停、软删除和风格配置。历史占位名等于code时仅在登录目录显示友好名称，不改数据库原名。
- 不运行 `create_all`，不 `stamp` 跳过迁移。API启动必须检查到0004。
- 不在本次任务中操作用户生产业务库。只验证了专用空schema的迁移与测试。
- 降级会去掉新增字段但不删除新增平台。由于旧版没有生成范围开关，**不能把降级当无损回滚**；须先停worker并审核新增平台启用状态，或采用经过演练的备份恢复。

## 新增接口与兼容

统一 `/api/v1`，旧前端 `/api` 别名仍可用。最新同源规范：`openapi-platform-login-v3-3.1.json`（113个路径）。

| 接口 | 权限 | 用途 |
|---|---|---|
| `GET /workspace/platforms` | admin/operator | 登录目录、启停、入口、扫码配置状态 |
| `POST /workspace/platforms` | admin | 保存自定义平台，默认不参与内容生成 |
| `POST /workspace/accounts` | admin | 增加可选login_hint、request_key；保留旧label调用 |
| `POST /workspace/accounts/{id}/login` | admin/operator | 发起真实登录，未过期扫码请求复用 |
| `POST /workspace/accounts/{id}/refresh` | admin/operator | 主动向适配器检查授权或会话 |
| `GET /workspace/accounts/{id}/session` | admin/operator | 本地状态、短期私有二维码URL，不查询远端 |

自定义平台请求示例（code可省略，此时按request_key稳定生成）：

```json
{"name":"企业社区","category":"other","login_url":"https://community.company.com/login","request_key":"a-unique-random-request-key"}
```

账号请求示例（platform_id用目录返回的真实ID）：

```json
{"platform_id":1,"label":"品牌主号","login_hint":"brand-account","request_key":"another-unique-random-key"}
```

平台设置的 `generation_enabled` 和 `login_url` 都是可选更新字段，旧客户端不传时不会清空/误开。只允许公开形式的HTTPS人工入口，不带用户名密码、查询参数、片段、非443端口、明显本机/私网地址或浏览器数字IP简写；不承诺验证域名实际归属或DNS解析结果。

## 真实扫码接入要求

需部署方通过安全环境配置提供：

- `BROWSER_ENABLED=true`
- `BROWSER_ADAPTER_URL`、`BROWSER_ADAPTER_TOKEN`
- 精确 `ADAPTER_ALLOWED_HOSTS`
- 有效且妥善备份的 `SESSION_ENCRYPTION_KEY`
- 私有对象存储，短期签名图片URL须能从用户浏览器访问
- 可选 `BROWSER_LOGIN_PLATFORMS=douyin,xhs,gzh`：明确服务已实现的code；留空兼容旧服务，**不表示所有平台都支持**。

服务须满足[二期适配协议](PHASE2_ADAPTERS.md)，并补充以下兼容约定：

1. `accounts/login` 的 `username` 可来自保存的login_hint，仅作提示；QR模式不转发密码。
2. `accounts/refresh` 现在也携带 `platform`，仍保留account_id/attempt_id，已登录时附加密会话解出的受管句柄。
3. 首次 `awaiting_scan` 必须给真实 `qr_png_base64`、attempt_id及带时区的有效expires_at。轮询等待响应可省略图片，但必须是已有未过期的同一次attempt，且不能靠无图响应延长期限。
4. `connected` 必须含非空真实session与有效期限。远端ID/扫码中/无会话不能记登录成功。
5. UI每3秒串行查一次，单次最多40轮；连续3个临时错误暂停，401/403/404/409/422/503直接暂停。停止查询不等于撤销远端在途请求；需要重新打开可复用未过期二维码继续查。
6. 二维码过期后本地直接过期，不继续刷新旧attempt；再次login取得新码。关闭弹窗、切换账号、离开页面都会停止本地轮询与倒计时。
7. 平台服务/存储/加密密钥缺失时明确报错，账号仍保存，没有伪造二维码或假“已登录”。

本仓库仍**不含**各平台页面选择器、官方App注册、独立可见浏览器适配服务。优先官方OAuth/API；网页接入必须在用户授权、平台规则允许的可见受管浏览器内进行，验证码或手机确认交还用户。不导出Cookie、不绕过验证码、不反检测。

## 验证结果（2026-11-10）

- 后端完整回归：**94 passed**（原73项 + 本次21项），SQLite内存隔离及真实PostgreSQL独立schema各一次；1条依赖弃用警告（Starlette/AnyIO旧别名）。
- Node轮询测试：**6 passed**，含主动refresh、成功/过期终态、关闭、切换账号、串行不重叠、次数上限、错误暂停。
- 专用PG schema `jiangguo_login_v3_upgrade`：0003→0004带历史账号、原名字/停用及软删除迁移；字段/状态/会话密文/版本保留，重复upgrade不重复建平台，`alembic check`无模型漂移。
- 受管共享浏览器：真实测试后端完成目录选择、自定义平台保存、刷新持久化、账号保存及缺配置无假码；1440×1000桌面与390×844手机账号弹窗检查，未出现JavaScript异常。
- 浏览器扫码“已授权/过期”使用**显式路由替身**；后端二维码与会话测试使用合成测试图片/适配替身，**不是抖音或其他平台真实扫码成功证据**。
- `python -m compileall`、相关ES modules语法、`git diff --check`；113路径OpenAPI 3.1结构校验通过。
- 未重测容器镜像构建，未合并、未生产部署、未做真实平台注册/扫码/发布验收。本次不重新声称全应用覆盖率或性能指标。

复测：

```bash
python -m pytest -q
node --test tests/test_qr_poller.mjs
# 真实PG必须使用独立测试schema，并显式设置APP_ENV=test / ALLOW_TEST_DATABASE_RESET=yes。
# tests/conftest.py会重建指定schema的表，绝不可对共享或业务schema运行！
```

浏览器脚本 `tests/browser/platform_login_smoke.py` 只连接平台提供的 `MANAGED_BROWSER_WS`，需要与实例一致的Playwright客户端，不launch私有浏览器。`TOKER_SMOKE_ISOLATED=yes`、`TOKER_SMOKE_URL`、`TOKER_SMOKE_USER`、`TOKER_SMOKE_PASSWORD`、`TOKER_SMOKE_OUT`由测试环境注入；不能填生产系统。测试新增的虚构账号/平台保留在独立schema，不删除历史。

## 业务验收建议

1. 查看平台列表并搜索；确认停用平台不能选，设置启用后可见。
2. 添加一次自定义平台，刷新页面再选择，确认没有影响每日生成范围。
3. 填账号保存；缺依赖时检查明确提示，账号只保存一次。
4. 安全接入一个真实平台后，真人手机扫码；核对实际授权昵称、过期重取、关闭/切换不会串号、退出确认真实撤销。
5. 前端负责人确认增量无冲突，维护者review后决定PR合入顺序与正式部署。最终真实扫码验收仍待完成。

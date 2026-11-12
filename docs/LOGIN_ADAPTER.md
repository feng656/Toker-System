# 内置平台扫码登录适配器

## 定位

`app/login_adapter.py` 是**可选的、本机回环监听**的受信浏览器适配器，用来把平台官方登录页里的二维码交给拓客系统展示。它只解决“扫码登录并保持受管会话”这一段，不替代平台发布 API，也不实现密码代填、验证码绕过、Cookie 导出或反检测。

默认不启用。没有配置 `BROWSER_ENABLED=true` 时 API 只保存平台账号，不生成二维码。

## 已核验平台

当前只启用并核验了：

- `douyin`：`https://creator.douyin.com/creator-micro/home` 官方创作者中心登录页。二维码由官方页面异步生成，正常在数秒内出现；适配器最多等待约 30 秒，并支持直接截取官方二维码容器作为兜底。

其他平台即使出现在登录目录里，也会由 `BROWSER_LOGIN_PLATFORMS` 判定为“尚未接入扫码服务”。新增平台必须同时满足：

1. 官方登录页直接展示可扫描二维码；
2. 适配器能从页面取得平台签发的二维码，而不是自绘占位图；
3. 能可靠判定登录完成（URL 或平台会话 Cookie 名称）；
4. 用真实账号完成一次扫码验收，并确认退出会关闭浏览器上下文。

不要把预置目录中的 15 个平台说成全部已接通。

## 运行方式

`scripts/start_platform.sh` 在 `BROWSER_ENABLED=true` 时后台启动：

```text
python -m app.login_adapter   # 127.0.0.1:${LOGIN_ADAPTER_PORT}
```

API 通过 `BROWSER_ADAPTER_URL=http://127.0.0.1:8400` 和 `BROWSER_ADAPTER_TOKEN` 调用 `/v2/accounts/login`、`/v2/accounts/refresh`、`/v2/accounts/logout`，协议见 [PHASE2_ADAPTERS.md](PHASE2_ADAPTERS.md)。

适配器启动时检查容器内 Chromium；起不来或健康检查超时会让容器启动失败，避免“页面显示健康但扫码一定失败”。

## 配置

```dotenv
BROWSER_ENABLED=true
BROWSER_ADAPTER_URL=http://127.0.0.1:8400
BROWSER_ADAPTER_TOKEN=<随机长令牌>
BROWSER_LOGIN_PLATFORMS=douyin
ADAPTER_ALLOWED_HOSTS=127.0.0.1
SESSION_ENCRYPTION_KEY=<Fernet密钥>
LOGIN_ADAPTER_PORT=8400
CHROMIUM_PATH=/usr/bin/chromium
LOGIN_QR_TTL_SECONDS=120
LOGIN_SESSION_TTL_HOURS=168
LOGIN_MAX_BROWSER_SESSIONS=4
```

- 令牌只放服务端环境，UI 不返回。
- `SESSION_ENCRYPTION_KEY` 必须是有效 Fernet key；缺失时 API 在发送任何登录请求前报 503。
- 适配器只监听 `127.0.0.1`，不要映射到公网端口。
- 容器需要额外内存供 Chromium 使用；部署时内存上限建议不低于 1536 MB。

## 会话与隐私

- 二维码通过 Playwright 从平台官方登录页的真实二维码图片取得；空白色块、纯色 logo 和装饰图会被过滤。
- 扫码在用户手机上完成；页面若要求短信、验证码或风控确认，交还用户在官方页面处理，适配器不尝试绕过。
- 同一账号短时间重复发起会重新打开登录页并替换旧二维码；如果平台因频繁访问暂时不生成二维码，稍后重试即可，适配器不会用占位图冒充二维码。
- 登录成功后，浏览器上下文留在适配器进程内，API 只保存 Fernet 加密的**不透明句柄**；不把 Cookie 写入数据库或返回前端。
- 适配器重启后旧句柄失效，前端会显示过期，需要重新扫码；这是有意的安全取舍。
- 同时保留的浏览器会话数受 `LOGIN_MAX_BROWSER_SESSIONS` 限制；退出账号会真正关闭对应上下文。

## 验收

1. 启动适配器后打开 `/health`，应返回 `{"ok": true, "platforms": ["douyin"]}`。
2. 在系统里选择抖音、保存账号，应显示平台官方二维码。
3. 用抖音 App 扫码并在手机确认；页面状态应在轮询后变为“已登录”。
4. 退出账号，再检查适配器日志无异常；旧二维码和会话都不应继续可用。
5. 其他平台应明确提示“该平台尚未接入扫码登录”，不能返回假二维码。

真实扫码完成依赖扫码人的手机和平台风控；仓库测试只能证明二维码来自官方页面及状态机正确，不能替代一次真人扫码验收。

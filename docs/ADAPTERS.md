# 外部适配契约与验收边界

## AI

`LLM_PROVIDERS`为最多3个OpenAI兼容服务配置，base_url接`/chat/completions`，每次调用超时LLM_TIMEOUT，JSON对象输出。失败切下一个服务；每次尝试保存ai_jobs，不记录密钥和原始提示词。无配置明确失败，不生成能误当真实内容的占位稿。DEMO_MODE仅开发/测试开启，日志demo=true。

### 平台模型网关（文案生成，推荐默认）

平台网关是OpenAI兼容接口，因此**不需要改 `app/llm.py`**：填 `PIOS_MODEL_KEY`（`pios model key` 自助签发，`mgk-` 开头）后，`LLM_PROVIDERS` 留空即自动生成两条 provider——主模型 `LLM_MODEL`（默认 `moonshotai/kimi-k3.1-pro`）+ 备用 `LLM_FALLBACK_MODEL`（默认 `qwen/qwen3.8-2.4t-a95b`），复用现有故障转移与 ai_jobs 审计。显式配置 `LLM_PROVIDERS` 时以显式配置为准。

### 平台视频生成（`app/video_provider.py`）

视频不在模型网关上，走平台 `/agent-api/video/*`：

- `POST {PIOS_API_URL}/agent-api/video/generate`，body `{async_mode:true, prompt, duration_sec, aspect_ratio, resolution?, model?, seed?, ref_image_base64?, watermark}` → `{success, data:{task_id, status, model_used, poll_url}}`；429/503 视为上游限流/队列满，带 `retry_after_s` 提示。
- `GET {PIOS_API_URL}/agent-api/video/tasks/{task_id}` → `{success, data:{status: pending|running|succeeded|failed|expired|cancelled, video_url|preview_url|signed_url|object_key|video_base64, duration_seconds, credits_charged, content_id, error}}`。平台统一用 `{success, message, data}` 信封，适配器自动解包（同时兼容直接返回业务字段）。轮询对 429/5xx 容错重试，`VIDEO_TIMEOUT` 到点报超时。
- 鉴权 `Authorization: Bearer {PIOS_TOKEN}`；`preview_url` 是 `/api/v1/...` 相对路径，下载前拼回 API 根。成片若托管在第三方 CDN（绝对 URL 非平台同源），下载时不携带平台令牌。
- 每次生成写一条 `ai_jobs(kind='video')`，失败只记异常类型，不落上游正文与凭据。
- 未配置 `PIOS_API_URL`/`PIOS_TOKEN` 时 `/video/generate` 返回 503；`app/video_gen.py` 的本地海报+ffmpeg 占位视频仅作为显式降级，不冒充真实成片。
- 默认 `VIDEO_MODEL=MiniMax-H3`、`VIDEO_RESOLUTION=2K`、`VIDEO_ASPECT_RATIO=9:16`（竖版短视频）；MiniMax-H3 目录仅支持 768P/2K，需要 1080P 时改 `doubao-seedance-2-0-mini-260615`。
- 主模型上游返回 502 时自动用 `VIDEO_FALLBACK_MODEL=doubao-seedance-2-0-mini-260615` + `VIDEO_FALLBACK_RESOLUTION=720P` 重试一次（2026-11-13 实测 MiniMax-H3 上游 502、豆包可用；豆包 mini 的 t2v 传 1080P 会 400）；429/503 是排队限流，不触发降级。

## OCR

本地Tesseract读取中英文截图，按行解析指标标签与数值单位（万/亿/w/k）。每个字段附0-1置信度，缺失值强制低置信；评论先按行给出建议，不能声称复杂评论布局能准确自动分栏，必须人工逐条校正。

HTTP适配由管理员配置受信OCR_ENDPOINT，不允许用户上传任意目标地址。POST multipart：`file`和`kind`，可选Bearer OCR_TOKEN，超时OCR_TIMEOUT。响应：

```json
{
  "text": "播放1000 点赞32",
  "fields": {"views":1000,"likes":32,"stat_date":"2026-11-03"},
  "confidence": {"views":0.94,"likes":0.91,"stat_date":0.75}
}
```

缺fields时按text解析；comments返回`fields.comments`数组及`confidence.comments`。上传截图必须先保存私有对象成功，否则503，不创建假成功任务。识别失败仍待审，保留错误，可retry或人工校录；confirmed之后才能写业务数据。

## 企微/CRM

WECOM_WEBHOOK使用机器人text格式，HTTP200仍须errcode=0。CRM_WEBHOOK接JSON线索快照，2xx成功且不能返回ok=false/success=false；接收端按Idempotency-Key去重，CRM_TOKEN可配置Bearer。失败不吞掉、不回滚线索，outbox保留attempts/error/due/status。测试覆盖503和企微业务错误，但本次没有真实机器人/CRM验收回执。

## 浏览器填稿（实验、默认关闭）

BROWSER_ADAPTER_URL是受控浏览器服务，由部署者接入可见/可接管的共享浏览器，不在API内私启隐藏浏览器。适配接口POST `/{platform}/open`、`/{platform}/screenshot`、`/{platform}/fill`，可带BROWSER_ADAPTER_TOKEN。fill请求仅发送数据库里审核通过的version数据，不接受前端传任意正文。

fill响应`{"ok":true,"published":false}`只写publish_status=filled；真正发布且返回公开HTTP(S) URL后才走同一record_publication。错误落publish_error，可重试。此仓库提供客户端契约，**未提供实际浏览器服务部署和各平台选择器验收**。

## 本机 Cookie 导入（扫码风控的人工验证兜底）

抖音等平台会对云端无头浏览器在手机确认阶段强制 ATO 网页安全验证（`account_flow=verify`、跳 `summon.bytedance.com` 滑块），云端环境无法自动完成。此时改由运营在本机 Chrome 完成扫码+滑块，再把已登录 Cookie 推送到系统；**云端适配器会实际打开平台验证登录态，验证不通过不会标记 connected**。

### 主 API：`POST /api/v1/workspace/accounts/{aid}/session-import`

鉴权：`Authorization: Bearer <运营/管理员 token>`（`operate` 权限）。
请求体（`extra=forbid`，Chrome `chrome.cookies.getAll()` 的字段可直接透传，未列字段会被忽略在 cookie 层）：

```json
{
  "platform": "douyin",
  "session": {
    "cookies": [
      {"name":"sessionid","value":"...","domain":".douyin.com","path":"/",
       "secure":true,"httpOnly":true,"sameSite":"no_restriction",
       "expirationDate":1790000000.0,"hostOnly":false,"session":false}
    ],
    "nickname": "可选：本机看到的昵称",
    "avatar_url": "可选"
  }
}
```

- `platform` 必须与账号平台一致，否则 409。
- Cookie 域名只允许 `douyin.com` / `amemv.com`（含子域）；必须包含 `sessionid` 或 `sessionid_ss`；最多 60 条、总名值 ≤64KB；`sameSite` 支持 `no_restriction|none|lax|strict`；`expires`/`expirationDate` 二选一，`session=true` 或非正数表示会话 Cookie。违规返回 422。
- 成功返回账号 JSON（`status=connected`，含 `nickname`、`session_expires_at`），**永不返回 Cookie 值或 `session_ciphertext`**。Cookie 与适配器会话句柄用 `SESSION_ENCRYPTION_KEY` Fernet 加密落库，审计事件 `session_import` 只记录平台、条数、Cookie 名和到期时间。
- 适配器校验失败 → 422「Cookie 未通过平台登录校验：<原因>」，账号保持原状态；适配器未配置 → 503；适配器网络/响应异常 → 502。
- 导入成功同时清空旧二维码与 `login_attempt_id`；之后 `POST /workspace/accounts/{aid}/refresh` 会在会话丢失时用库内 Cookie 重建浏览器上下文。

### 登录适配器：`POST /v2/accounts/import`

主 API 调用；`Authorization: Bearer BROWSER_ADAPTER_TOKEN`。

```json
{"account_id": 1, "platform": "douyin", "cookies": [{"name":"sessionid","value":"...","domain":".douyin.com","path":"/","secure":true,"httpOnly":true}]}
```

响应 `{"ok":true,"status":"connected","session":{"handle":"..."},"nickname":"...","expires_at":"..."}`；Cookie 失效时 `{"ok":true,"status":"invalid","error":"..."}`。适配器会新建 stealth Chromium 上下文、写入 Cookie、打开平台创作者页并检测登录态，成功后保留该上下文供后续发布/刷新复用。

`POST /v2/accounts/refresh` 新增可选 `session`（库内解密后的 `{handle,cookies,source}`）与 `platform`：适配器进程重启、内存会话丢失时，用 `session.cookies` 重新初始化并返回 `connected`；没有 Cookie 才返回 `expired`。

### 沙盒发布：`publish/prepare`

`workspace.run_publish` 的 `publish/prepare` 载荷本就包含 `session`（`account_payload` 返回 `{account_id,platform,session}`）。导入的会话形如：

```json
{"handle":"...","cookies":[{"name":"sessionid","value":"...","domain":".douyin.com","path":"/","secure":true,"httpOnly":true,"sameSite":"None"}],"source":"cookie_import"}
```

沙盒发布适配器打开 `creator.douyin.com` 前必须 `context.add_cookies(session.cookies)`；若与登录适配器同进程同实例，可直接复用 `session.handle` 对应的上下文。**本仓库只实现登录/校验适配器（`app/login_adapter.py`），`publish/prepare`、`publish/confirm` 由部署侧沙盒发布适配器实现，各平台选择器需单独验收。**

## 官方发布（实验、默认关闭）

现有gzh/douyin客户端保留，默认OFFICIAL_PUBLISH_ENABLED=false。异步提交仅写submitted及远端标识，内部media_id/item_id不做公开URL，不计发布量。平台素材、授权、封面等前提可能导致请求被拒；失败记录可见。生产启用前需按平台最新规范对凭据、素材和发布回调单独验收，本次不宣称真实自动发布可用。

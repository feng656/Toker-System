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

## 官方发布（实验、默认关闭）

现有gzh/douyin客户端保留，默认OFFICIAL_PUBLISH_ENABLED=false。异步提交仅写submitted及远端标识，内部media_id/item_id不做公开URL，不计发布量。平台素材、授权、封面等前提可能导致请求被拒；失败记录可见。生产启用前需按平台最新规范对凭据、素材和发布回调单独验收，本次不宣称真实自动发布可用。

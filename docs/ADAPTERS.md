# 外部适配契约与验收边界

## AI

`LLM_PROVIDERS`为最多3个OpenAI兼容服务配置，base_url接`/chat/completions`，每次调用超时LLM_TIMEOUT，JSON对象输出。失败切下一个服务；每次尝试保存ai_jobs，不记录密钥和原始提示词。无配置明确失败，不生成能误当真实内容的占位稿。DEMO_MODE仅开发/测试开启，日志demo=true。

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

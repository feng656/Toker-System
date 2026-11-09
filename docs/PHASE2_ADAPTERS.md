# 二期适配协议与联调边界

## 实施状态
本仓库已实现客户端、持久化任务、安全控制与HTTP协议测试，**不含各网站页面选择器、抖音开放平台App注册或独立受管浏览器服务**。这部分需奇迹提供已授权账号及受信适配服务，再按本协议联调；不能把客户端完成说成真实扫码/发布成功。生产优先采用平台官方授权/API；网页适配须核对平台条款并可见、可接管。不提供隐身、Cookie导出、验证码绕过、反检测或伪装访问功能。

## 共同约束
- 浏览器根地址 `BROWSER_ADAPTER_URL`、Token、Fernet会话密钥仅在环境配置；请求 `Authorization: Bearer …`。
- 所有浏览器请求 `POST {base}/v2/{action}`，JSON；响应必须 `ok:true`。超时60秒，不跟随重定向，错误不回显原始响应或密钥。
- `ADAPTER_ALLOWED_HOSTS` 是部署方设置的精确主机白名单；适配/AI端点必须在其中，URL不得有用户信息或查询参数。媒体下载使用独立 `MEDIA_ALLOWED_HOSTS`。建议仅HTTPS；私网HTTP仅允许受控隔离网络，出站防火墙限制地址/端口，避免DNS重新绑定。
- key_env只接受 `TOKER_AI_KEY_*`，不可引用任意服务器环境变量。UI保存的是引用名，不是key明文。旧 `LLM_PROVIDERS` 环境配置仍兼容。
- 发送/发布/视频创建请求含稳定 `Idempotency-Key`。服务端必须持久化该键及响应；**不实现幂等的适配服务不可接入**。请求超时不能认定未发送。
- 每个账号隔离session。后端优先保存受管浏览器会话句柄，不需要本机Cookie；服务必须禁止账号间串用。会话本地Fernet加密，API永不返回解密内容。
- 二期公共时间沿用一期“无时区字段保存UTC”的约定；登录适配响应期限必须带时区。全库UUIDv7/timestamptz仍是一期审计后续项，本次未做破坏式转换。

## 登录
`accounts/login` 输入 account_id/platform/mode(qr|password)/username/password。账密不落库、日志、审计和响应。二维码不是本服务自行绘制：

```json
{"ok":true,"status":"awaiting_scan","attempt_id":"remote-attempt","qr_png_base64":"真实PNG的base64","expires_at":"2026-12-01T10:05:00Z"}
```

`accounts/refresh` 输入account_id/attempt_id；已登录时附session。扫码完成：

```json
{"ok":true,"status":"connected","session":{"handle":"opaque-session-handle"},"nickname":"账号昵称","avatar_url":"https://授权平台/avatar","expires_at":"2026-12-01T12:00:00Z"}
```

也可返回status=expired。GET `/workspace/accounts/{id}/session`只读取本地状态和短期签名二维码；前端可按服务规定有界调用refresh，二维码过期重新login。`accounts/logout`必须真正撤销远端会话并返回ok；后端随后清空本地加密信息。

## 发布
1. POST `/workspace/publish-jobs`建立同平台已审核内容的队列任务。
2. `publish/prepare` 输入account_id/platform/session/variant_id/title/body/hashtags/assets[{kind,url}]/submit=false。必须只填稿，禁止提交。
3. 返回status=awaiting_confirmation、job_id、confirmation_token、steps。steps最多20项，每项name/status/screenshot_png_base64；至少一张真实步骤图，写私有存储。
4. 操作者检查截图，调用 `/workspace/publish-jobs/{id}/confirm`。后端重新验证审核、合规、素材公开许可及内容指纹，再发 `publish/confirm`，携带remote_job_id/confirmation_token/human_confirmed=true。
5. 仅status=published + 公开形式url + 截图证据才能记发布；URL格式校验不等同于远程文章存在性/归属验证。
6. confirm结果不确定，保留awaiting_confirmation及同一键；不能重建任务盲发。人工取消只停止本地后续执行，不承诺删除远端草稿。

旧 `/browser/{platform}/publish` 只兼容填稿，不再接受适配器直接返回published跳过人工确认；正式发布请用新接口。

## 授权评论
- `comments/discover` 输入账号会话/keyword/limit/date_from/sort/human_search_confirmed。只读用户已确认的搜索页，返回最多5个targets：id/url/title/authorized=true/authorization_ref。授权应是自有内容或有明确互动许可，不是“平台页面公开即可营销”。
- prepare最多生成每目标10条；manual模式每行一条；polish/ai使用文本适配。硬性合规+历史5000条相似度≥0.88过滤+全轮去重。宁可少于50条，也不复制凑数。
- approve必须由运营逐批确认当前目标与文案，AI不能替人审批。
- `comments/send` 输入target_id/authorization_ref/body/human_approved及账号会话。响应status=sent/comment_id。
- 每次run只发一条，不使用阻塞sleep；单副本worker每30秒调度一次，账号默认至少60秒间隔、24小时最多50条，评论与私信共用额度。平台限制更严时调低。
- stop/cancel停止后续发送；已在途的一条可能已发送，保留实际结果。sending中断15分钟后标记uncertain，worker不自动重发，人工核对后同任务run复用幂等键。
- `comments/replies` 只查询本任务已发送comment_ids。返回replies，每项id/parent_comment_id/sender_id/body；幂等写Interaction→分类→去重Lead→TopicSuggestion。不是抓取全部评论。

## 私信
`POST /dm/messages` 是运营权限的入站录入/服务转交接口，不是匿名Webhook；source_key按账号命名空间哈希后幂等。尚未内置某平台私信Webhook签名验签及主动拉取实现，接入端必须先验签并使用受限服务账号。

政策：账号+fixed/ai+template_id/provider_id+persona+明确sender_id范围+时间窗（Asia/Shanghai）；空范围不发送。固定话术与AI都先prepare、人工approve后才send；AI的“自动接管”在本批被保守限定为**自动生成候选、批准后自动投递**，不是无人审核回复。涉及密码、验证码、转账、银行卡、退款、投诉、诉讼等转人工，不能直接approve绕过。

`dm/send` 输入账号会话/sender_id/body/human_approved，响应status=sent/message_id。准备、审批、投递、失败有automation_events审计，明文消息只对运营可见。

## 视频
统一“jobs适配层”，不是直接兼容任意供应商原生协议：
- `POST {endpoint}/jobs`：prompt/model，图生视频另有10分钟image_url；Idempotency-Key为video:request_key。
- 接受后返回 `{job_id,status:queued|running|succeeded,output_url?}`。
- 查询 `GET {endpoint}/jobs/{job_id}` 返回同状态；succeeded必须含output_url。
- 创建阶段明确404/429/503拒绝可按priority尝试最多3家；网络结果不确定或已受理后固定提供方，不跨服务重复扣费。重试沿用同一个键。
- 产物下载不跟重定向，最多100MiB，ffprobe本地检查视频流、时长0–600秒、边长≤7680、MP4/WebM容器后才入私有素材。默认internal，人工批准public后才能用于外发。
- 文案选图使用人工标题/标签/类别作为上下文，不是视觉识图。原始图片不自动发文本AI，不能声称理解了图片细节。

## 调度开关
API进程 `SCHEDULER_ENABLED=false`，单独 `python -m app.worker`。`PHASE2_WORKER_ENABLED=true`才处理已入队视频、发布预览及批准的互动；`AUTOMATION_ENABLED=true`才外发评论/私信。默认均关闭。状态/审计接口用于前端显示失败与人工待处理，不隐藏外部依赖错误。

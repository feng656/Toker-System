# 二期后端接口契约（接口先行）

基线main：23fe5418a80117ce38ee6e23b746502f388fbbca。只修改后端、迁移、测试、脚本和接口文档，不修改web。旧/api和/api/v1保持同一业务实现。旧平台字符串保留为兼容code，新增platform_id为关联键。

## R10 登录安全
- GET /auth/policy：只公开自动注册开关、挑战方式和限额，不返回密钥。
- POST /auth/challenge：创建绑定客户端地址、有期限、一次性的SHA256工作量挑战。challenge_id/nonce/difficulty/expires_at返回；登录可带challenge_id/challenge_solution。
- POST /auth/login：原username/password兼容；IP+账号双限流、失败退避。自动注册默认off，可用invite模式，必须邀请码且只能最低权限sales。API不允许任意改自动注册策略。

## R1 动态平台
- GET /platforms?enabled=；GET /platforms/templates；POST /platforms；PUT /platforms/{id}。
- 平台字段：code(唯一、稳定)、name、icon、category、publish_mode(manual/sandbox/api)、default_time、style_prompt、enabled。
- 模板：四个默认平台及taobao/xhs/kuaishou/bilibili；新增平台自动进入后续内容包，每选题×启用平台；旧历史平台/链接/统计不变。停用不删除历史。

## R4/R8 内容查询与批量审核
- GET /variants：platform_id/platform/status/confirm_status/scheduled_from/scheduled_to/min_score/max_score/compliance_ok/current，返回items/total/limit/offset。
- GET /variants/{id}；POST /variants/bulk-review：variant_ids/action/reason/expected_versions，最多100条，去重、整批预检，禁止绕过blocked。expected_versions必须覆盖整批ID；缺失返回422，过期409。
- POST /contents/drafts：人工草稿，平台和素材引用，仍须质检审批；GET /contents保留旧返回格式并扩展筛选。
- GET /topic-suggestions；POST /topic-suggestions/{id}/convert：将真实需求建议幂等转选题。

## R9 AI与R3素材
- GET/POST /ai/providers；PUT /ai/providers/{id}；POST /ai/providers/{id}/test。
- 配置能力text/video、endpoint/model/priority/key_env；key_env仅允许TOKER_AI_KEY_*。只保存环境变量引用，不在DB明文保存key；配置返回configured布尔值，永不返回密钥。text沿用OpenAI兼容契约，video使用明确的jobs适配。端点须在部署方ADAPTER_ALLOWED_HOSTS白名单内，不能从UI任意出站。
- POST /assets/upload：multipart files，每批1–20张JPEG/PNG/WebP，私有存储、标签、公开级别。GET /assets；PUT /assets/{id}修改标题/权限/标签；GET /assets/{id}/url；GET /assets/{id}/usage。
- POST /assets/generate-content：request_key/topic_id/platform_id/asset_ids/scheduled_date，按授权图片的人工标题与标签生成文案并记录引用，不声称视觉识图。POST /variants/{id}/assets关联公开素材后撤销原审批。
- GET /video-jobs返回任务列表；GET /dashboard/platforms按platform_id汇总，不丢停用平台历史。
- POST /video-jobs：prompt/image_asset_id/platform_id/provider_id；GET /video-jobs/{id}；POST /video-jobs/{id}/run、/retry。产物实际下载校验后才入素材，不以远端任务ID冒充成品。

## R2/R6沙盒与扫码
- GET/POST /workspace/accounts：一个平台可有多个账号。POST /workspace/accounts/{id}/login、/refresh、/logout；GET /workspace/accounts/{id}/session。
- POST login：login_mode=qr/password；密码只转发受信适配，不回显、不落日志。adapter返回真实二维码和到期时间；会话Cookie/远端句柄Fernet加密存储。未配适配返回503，绝不返回假二维码。
- POST /workspace/publish-jobs：variant_id/account_id；POST /workspace/publish-jobs/{id}/run、/confirm、/retry；GET /workspace/overview。
- 发布进入人工确认后才允许最终提交；每个步骤截图先保存私有对象，公开URL通过原回填校验后才计发布。状态queued/running/awaiting_confirmation/succeeded/failed/cancelled。

## R7 评论任务（仅经授权互动）
- POST /comment-tasks：account_id/keyword/video_limit<=5/comments_per_video<=10/mode(manual/polish/ai)/draft。
- POST /comment-tasks/{id}/discover：由用户先在受控页面确认搜索，adapter仅返回已授权目标；不抓取全站。
- POST /comment-tasks/{id}/prepare：生成候选文案、历史相似度过滤、合规检查。GET /comment-tasks/{id}查看逐条目标和文案。
- POST /comment-tasks/{id}/approve：明确授权目标与文案；POST /comment-tasks/{id}/run逐条有界发送，停止/取消接口。无授权不得发送；不提供防检测伪装或绕验证码。
- POST /comment-tasks/{id}/collect：受信平台返回的入站回复经AI识别，进入原互动/去重线索与需求建议。

## R11 私信
- GET/POST /reply-templates；GET/POST /dm-policies：account_id/mode(fixed/ai)/provider_id/persona/window_start/window_end/scope。
- POST /dm/messages：入站事件id幂等；POST /dm/messages/{id}/prepare：只对授权范围内入站消息生成候选，高风险转人工；POST /dm/messages/{id}/approve、/send。账号与发送授权不由AI决定，全部留痕。

## 调度与审计补充
- GET /automation/events?resource=&resource_id=：授权操作和发送结果审计。
- POST /workspace/publish-jobs/{id}/cancel；GET /workspace/publish-jobs/{id}；GET /workspace/publish-jobs/{id}/steps/{index}/screenshot提供10分钟签名截图。
- POST /comment-tasks/{id}/stop、/cancel：停止后续发送，已在途单条不承诺撤销。run每次最多一条。
- GET /dm/messages、GET /comment-tasks、PUT /reply-templates/{id}供列表/编辑。
- 二期worker默认关闭；开启后只消费已入队或已人工批准任务，不自动审批。sending中断转uncertain，不自动重发；私信窗口按Asia/Shanghai。
- 完整HTTP契约及未实现的平台端能力见[PHASE2_ADAPTERS.md](PHASE2_ADAPTERS.md)，升级和镜像见[PHASE2_DEPLOYMENT.md](PHASE2_DEPLOYMENT.md)。

## 外部依赖与安全
沙盒/扫码/评论/私信由同一个受信BROWSER_ADAPTER服务接入可见、可接管的受管浏览器。此仓库不会私启隐藏浏览器或导出本机登录Cookie。未提供该服务和账号前，只能完成接口/队列/状态/适配协议测试，不能声称真实平台端到端通过。R5需提供Gitee目标仓库与授权；脚本不修改hosts、不关闭TLS、不强推或删除远端分支。R12只引用开源架构与许可证，不复制限制协议代码。

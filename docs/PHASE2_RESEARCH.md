# R12 技术调研与取舍

核对日期：2026-11-09。资料来源为对应GitHub仓库README、仓库元数据及LICENSE文件（通过GitHub API读取）。未运行这些项目，未进行抖音平台兼容测试，也未复制它们的实现代码。

| 项目/来源 | 核实的定位与许可 | 可借鉴的设计思想 | 对应本项目/取舍 |
|---|---|---|---|
| [Postiz](https://github.com/gitroomhq/postiz-app) · [许可](https://github.com/gitroomhq/postiz-app/blob/main/LICENSE) | 社媒排期、分析、团队协作；README列NestJS/Prisma/PostgreSQL/Temporal。AGPL-3.0 | 平台连接、排期任务、内容与发布渠道分离；官方授权优先 | R1/R2/R4：保留动态平台+账号+发布任务独立表；不移植代码，不把其TikTok支持说成抖音已支持 |
| [Browserless](https://github.com/browserless/browserless) · [许可](https://github.com/browserless/browserless/blob/main/LICENSE) | 浏览器远程连接、并发排队、Debug Viewer和超时；SSPL-1.0或商业授权 | 浏览器服务与业务后端分离、可视调试、会话超时 | R2/R6：定义受信适配协议、加密句柄、截图存证；不打包该软件、不复制实现；商业闭源集成须先评估授权 |
| [Dify](https://github.com/langgenius/dify) · [许可](https://github.com/langgenius/dify/blob/main/LICENSE) | AI应用、模型管理、工作流与可观测性；修改版Apache 2.0附额外条件 | 将业务提示与供应商配置分离、统一调用与失败审计 | R9/R11：按文本/视频能力配置、提供方选择与人设；不替换现有FastAPI体系，不复制代码。许可证含多租户和前端标识限制，不能当成普通Apache 2.0 |
| [aiojobs](https://github.com/aio-libs/aiojobs) · [许可](https://github.com/aio-libs/aiojobs/blob/master/LICENSE) | asyncio后台任务管理、受控调度、优雅关闭；Apache-2.0 | 控制并发、跟踪在途任务、退出时等待的重要性 | R2/R7：沿用持久化PG任务和单副本worker，显式sending/uncertain状态；未引入额外依赖。其进程内队列不能代替业务持久化 |

## 不采用的方向
- 不实现“防封保证”、代理池轮换、隐藏指纹、伪造真人行为、验证码绕过。低频只能降低打扰与负载，不能使违反平台条款的操作合法化。
- 不把公开评论区当作无限授权营销目标；需要自有或明确许可目标、人工确认、可取消、额度和逐条审计。
- 不为借鉴队列更换整个技术栈；FastAPI、PostgreSQL、MinIO和现有调度器可支撑本期增量。
- 不承诺任意网络环境都能访问仓库；Gitee镜像是额外通路，PR审核仍在GitHub，镜像代码不会自动迁移PR讨论。

## 后续技术验证门
1. 提供有许可的受管浏览器服务，验证账号隔离、真实二维码期限、人工接管和幂等缓存。
2. 抖音真实账号做单条发布/单条互动，再经业务确认逐步增量；不要直接以50条为首次实测目标。
3. 视频供应商原生响应与本仓库jobs协议映射后，验证提交超时和重复查询不重复扣费。
4. 如考虑使用上列项目源码或商业服务，单独进行许可证与平台协议评估；本调研不是法律意见。

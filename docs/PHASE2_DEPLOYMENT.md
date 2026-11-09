# 二期升级与协作指南

## 版本边界
基于双方已合并的main `23fe5418a80117ce38ee6e23b746502f388fbbca` 增量开发。只改后端、迁移、脚本、测试和文档；`web/`整树保持基线不变。新页面由前端负责人按[契约](PHASE2_API_CONTRACT.md)及`openapi-phase2-3.1.json`联调。本批不是可直接声称抖音真机验收通过的上线版本。

## 升级步骤
1. 维护窗口停止API与worker，对业务PostgreSQL及MinIO做可恢复备份；不要把验证脚本指向生产。
2. 安装`requirements.txt`和系统`ffmpeg`（含ffprobe）、Tesseract；Python 3.11。
3. 按`.env.example`补二期环境变量。自动注册默认off；若产品批准invite模式，设置随机邀请码，账号仅sales角色。
4. 执行`python -m alembic upgrade head`，预期版本`0003_phase2`。该迁移创建二期表，扩大平台code字段，回填platform_id；四个平台默认启用，小红书保留为停用兼容平台；其余历史code保留但停用。
5. `python -m alembic check`确认模型无漂移；`python -m scripts.seed`补缺省平台（不使用demo参数初始化生产）。禁止直接stamp跳过迁移。
6. API使用`SCHEDULER_ENABLED=false`；只启动一个`python -m app.worker`。二期worker和互动发送默认关闭，经确认后分别启用。
7. 先验证登录、生成、审批、人工回填和旧入口，再对接二期页面，最后配置真实外部服务。

迁移已验证空库及带历史发布/指标记录的独立PG schema；**没有操作用户现有业务库**。回退0003会删除二期数据，不能未备份直接downgrade；推荐回滚应用前先确认数据兼容，必要时从备份恢复。SQLite仅内存测试用，batch重建临时关闭FK是测试夹具行为，不用于生产。

## 安全上线要求
- 以网关限制请求体、连接数、速率，API不直接暴露到公网。应用IP取真实连接地址，忽略不可信X-Forwarded-For；反向代理必须明确可信边界，否则同一代理下共享IP限额。
- 密码校验进程内最大4并发；IP/账号次数与失败退避在PG持久化，挑战5分钟有效且一次性绑定IP。此为应用层防护，不宣称能抵御大规模DDoS。
- 私有MinIO只能通过10分钟签名链接访问；前端不可把session、邀请码或供应商key写进localStorage、日志、截图。
- Fernet密钥与数据库备份分别保管；轮换后旧会话须重新登录。本版没有自动多密钥轮换功能。
- 限制AI/适配服务主机白名单与出站网络；只将`TOKER_AI_KEY_*`用于AI服务，不允许引用JWT/数据库密码等环境变量。
- `POST /dm/messages`需要运营认证；若开放平台Webhook，另行在适配层做签名验签、重放保护，不能直接公开此接口。
- 生成图片/视频默认internal；批准公开后再关联内容发布；关联素材会撤销原审批。
- 当前整数主键/UTC无时区字段、旧官方API账号模型及一期未完成项没有在本批全库重构，需继续做生产安全评估。

## Gitee镜像（R5）
当前没有提供目标仓库和授权，**未创建或推送Gitee镜像**。脚本只按明确分支快进推送，默认dry-run：

```bash
python scripts/sync_mirror.py --target https://gitee.com/组织/仓库.git --branch main
python scripts/sync_mirror.py --target https://gitee.com/组织/仓库.git --branch main --execute
```

由维护者先创建镜像、配置Git credential helper或CI secret+GIT_ASKPASS；不要把令牌写进URL、参数或仓库。分支有分叉时脚本失败并停下，不强推、不删分支、不改hosts、不禁TLS。CI如需自动同步，应在人工审查合并main后调用，未经维护者授权不新增含凭据的定时任务。

GitHub页面不可达时可用正常`gh`/GitHub API读取PR；Gitee只镜像代码，**不是PR页面镜像，也不能保证任意网络100%可用**。

## 开发自测
```bash
python -m pytest -q
python -m scripts.e2e_demo --mode isolated --out reports/e2e-phase2-compat.json
```

真实PG测试每项会重置schema，必须设`APP_ENV=test`、`ALLOW_TEST_DATABASE_RESET=yes`，数据库连接必须限定独立`search_path`，严禁生产/共享业务schema。本次使用`jiangguo_phase2_validation`；带历史数据迁移脚本只允许空的`jiangguo_phase2_upgrade_validation`。

## 还需要业务方提供
- Gitee目标仓库与标准授权；真实可见浏览器适配服务及平台操作许可。
- 抖音测试账号（通过真实扫码，不交出密码或导出本机Cookie）。
- 文本与视频服务key，通过环境安全配置；视频服务需映射jobs协议。
- 公司已授权图片、真实平台测试内容、头条参考文章原文/截图。
- 产品确认自动注册策略及私信人工审批边界；本批不开放无人审核自动外发。

# 当前设计：1.3.2 / schema 5

FastAPI/Jinja2 Web、一个 Worker、SQLite、SMTP/IMAP 构成单机系统。源码版本、数据库 schema5、来源验证v3、生成合同3是不同概念。

- `Researcher` 保存受限原文快照；`qualification` 独立判断相关性与联系资格。`candidate_lifecycle` 归档过期未发候选，保留证据和去重；活跃待核/可起草/排队共用2000人容量。
- `Engine` 复用 `Generation` 的简报、完整文案、独立审核与版本绑定。模型不决定收件地址，不创建许可，不执行来信中的工具命令。
- `InitialPipeline` 使用 jobs 表持久化 brief/compose/review；`ReplyPipeline` 持久化 classify/compose/review，每阶段一个模型请求。失败与一次改写有界；新来信、证据、配置或相关Profile变更使旧结果失效。
- Worker先按小时门槛同步邮箱，尝试发送到期邮件，再优先执行来信任务。研究按周期继续补充，不必等待所有合资格首信起草完毕。每轮100秒；SMTP uncertain不进入自动重试。
- 六类模型任务显式路由到 Profile，密钥加密存储，按实际协议发送参数。研究及首封受营销预算约束，回复相关调用不占营销额度；不代表提供方无限制。
- 来信处理：明确拒绝停发且不回复；普通问题通过配置模型撰写与独立审核；身份/意图不明、敏感请求、失败或超轮次转人工。自动通知保持忽略路径。不存在自动追催未回复联系人。
- 模型审核记录不可变；当前正文、来源、事实/提示词、Profile、许可、来信和身份配置形成新的审核绑定。所有模式都强制AI与程序检查，review另外需要人工批准。
- 所有新安装自动化默认关闭。授权启用后跨重启保存；每小时IMAP、75分钟健康门槛、默认2轮自动回复、每日首封≤10、最短61分钟和停发保护持续生效。
- 研究国家默认US，可选13国；当前画像6/3/1轮换为技术、成年儿童AI教育工作者和相邻业务/创作人群。未成年人不是发信对象。
- schema1/2/3/4→5迁移保留UID、证据、密钥、MIME、计数和停发，暂停自动化、暂缓旧草稿、将未决发送记为uncertain。schema5不能直接降级。默认Compose保留Tailscale绑定和私有卷。
- 归档不删除可追溯来源。显式匿名化仍清除个人内容并保留停发哈希；私有备份包含敏感材料，不进入Git。公共 history为空。

详见 [邮件生成](EMAIL_GENERATION.md)、[模型路由](MODEL_ROUTING.md)、[候选池](CANDIDATE_POOL_2000.md)、[来信处理](CONTINUOUS_REPLY_TRIAGE.md)、[当前测试](TEST_REPORT.md)。历史规格与验收入口见 [文档索引](INDEX.md)。

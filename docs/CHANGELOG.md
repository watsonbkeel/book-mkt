# Continuous reply triage

- Expose stop-contact / automatic-reply / human handling in the inbox and message detail, retain refusal evidence, and distinguish a negative answer about KU from declining contact in the classification prompt.
- Prioritize durable reply stages over research work; deduplicate by inbound ID across stages. A manual case does not block other messages. Classification version invalidates old reply reviews only.
- Status output reads the actual database schema. Existing automation defaults, migration pause, send limits, mailbox checks and suppression remain unchanged.
- Production classification/reply/review use the author's existing Sonnet Profile; continued operation is explicitly authorized by the author. No new provider or synthetic test email is required.

# Editorial positioning preview history

- Versioned author positioning now describes capability expansion through planning, multiple advisor challenges, human choices, execution and independent checks. The same source informs briefs, complete first messages, independent review, approved teaching examples and replies.
- First-message body range is 80–120 words. New positioning/prompt versions invalidate old unsent approvals; old approved examples require current book/policy/source review binding before a new offer.
- Exact fresh `Nope` triggers suppression without a reply. Synthetic editorial preview tooling uses the existing generation entry points and forbids SMTP/IMAP connections. No production deployment or queue change is part of this preview.
- A chapter recommendation now binds one promised chapter and replies must deliver it. Independent review rejects unsupported performance comparisons; the first live preview exposed this promise mismatch and was superseded before editorial delivery.

# 1.3.2 (2026-09-25)

- 研究启用时，待核候选由当前 `review` 任务 Profile 提议来源原文摘录，再经现有资格校验器核实；模型结果不能创建许可或修改停发记录。每位候选自动重试间隔7天，全局每5分钟至多安排一位，仍受每日预算约束。
- 对1.3.1升级暂缓、未尝试发送且来源资格仍有效的 AI 首信安排一次独立审核；审核通过才进入现有发送队列。
- 收件身份、DMARC、Reply-To、退订、敏感请求、第三轮自动回复和 SMTP 结果不确定仍按原有安全规则处理。

# Local pending authorization — candidate qualification

- Change research profile selection to a repeating 6/3/1 split across ten attempts while retaining all thirteen countries, the configured research period, and existing budgets.
- Separate source-backed profile fit from contact permission. Preserve high-relevance candidates with evidence/permission tasks and block them from Worker drafting until all checks pass.
- Save bounded research snapshots even when the proposed fit quote misses; add authenticated snapshot quote verification and candidate qualification counts.
- Permit official school/employer staff pages to establish identity and current role across different profile/email domains. Keep source-domain, published-email, MX, location, role-mailbox, source-restriction, opt-out, and contact-permission guards.
- No database schema change. Local tests only; no live search, API call, mailbox access, message delivery, or deployment.

# 1.3.0 — evidence-to-email upgrade (2026-09-25)

- Add bounded research snapshots, evidence briefs, complete model-written subject/body and one directed revision. Preserve actual prose and final MIME.
- Extend existing initial/reply review across all three modes, version/hash-bound approvals, editable recheck/redraft and explicit manual reply responsibility.
- Add approved original example assets, saved invitation offers and reply fulfillment; preserve inbound uniqueness, new-inbound invalidation and refusal priority.
- Add encrypted per-task profiles, protocol effort/thinking payloads, budgets/timeouts and sanitized usage observability. Legacy account/model settings migrate without new provider selection.
- Separate draft errors from consent. Add schema4 migration,1.2 upgrade/empty-target rollback, privacy retention, mock blind comparison and local browser checks.
- Preserve thirteen-country adult research, US-public/consent limits, hourly IMAP, send caps, SMTP uncertainty and Tailscale binding.

Previous releases below are historical.

# v1.2.0 — 2026-09-24

- 新安装默认美东08:30–19:30；旧配置保留，新增确认后暂停的预设切换。
- 来源所在地支持城市+州，补客户/活动/否定/外国冲突检查，证据v3及schema3安全迁移。
- 首封源文主题、自然开场、四步法、三画像价值说明与发送前标题保护。
- Brave沿实际同站Contact/About/Team链接有界读取；Anthropic原生基础web_search及有界多轮续接。
- 核心小模块按职责拆分，保留小时收信、限额、SMTP不确定不重试、线程验证和退订保护。
- 原12人历史和18章目录未改；当前实际验证见TEST_REPORT。

---
以下为历史v1.1变更记录，不覆盖以上现状。

# v1.1.0 — 2026-09-24

## 核心需求
- IMAP改为固定每60分钟，持久化尝试时间；手动同步/重启不绕过，失败不密集重试。
- 健康阈值从10分钟改75分钟；失败/积压/缺口即时阻断外发。换邮箱清旧健康证据。

## 研究与邮件
- MX/Null MX与异常状态、禁止收集/推销声明、专用角色邮箱过滤。
- 同业务域365天冷却和队列占位；匿名地址按原哈希去重。
- 首封主体<=120词，完整书名/副标题/作者/Amazon；个性化从已核实短原文提取，两次失败停止。
- 分类模型独立配置，Anthropic Messages+Brave适配；兼容模式reasoning开关，模型用途/Token日志。
- 默认自动回复总上限2；第3轮转人工。附件EML不作为新来信，自动通知不计人类回信；发送时重查DMARC策略。
- SMTP拒绝、临时拒绝、策略/认证拒绝与结果不确定分离，均不自动重发。
- 新增可关联DSN/ARF/人工投诉事件与保守熔断；退订不发额外确认，停发立即拦截后续队列。

## 网页与运维
- 待审编辑→再批准；已发/不确定正文不允许编辑。
- 分类筛选、分期事件统计、同批次回复率、折线图、小时收信/容量提示。
- 熔断证据解除、收信缺口核对、投诉手工登记、来源重新核验。
- Schema1→2自动安全迁移，原密钥/游标/历史保留；全自动化暂停，旧待发held。
- 提供保留原卷的升级脚本及回退文档；不改Nginx、外部业务或出版定位。
- 最终119项测试；9页18次浏览器内容渲染。真实服务/容器联调仍待部署者验证。
# 1.3.1 — remaining fixes (2026-09-25)

- Give reply generation/review the fixed Amazon URL without exposing it to initial drafts; reject other links and expired KU claims.
- Add audited manual reply takeover that preserves superseded AI drafts and reviews, and keeps suppression, recipient, threading and SMTP uncertainty checks.
- Apply configurable per-dimension and mean quality floors to new and stored reviews. Previously approved low-score drafts lose approval and require recheck.
- Stage reply classification, composition and review as durable Worker jobs, one model call per turn.
- Default research to the US, allow selected-country rotation, and provide confirmed out-of-scope candidate archival without deleting history.
- Check actual task Profiles before enabling work; retain unrelated Legacy Profile settings when classification model changes.
- Unify qualification inputs and add an aggregate-only `qualification-report` CLI. Schema 4→5 pauses automation and holds pending drafts.

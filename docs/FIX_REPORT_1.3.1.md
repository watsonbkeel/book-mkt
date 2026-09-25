# book-mkt 1.3.1 修复报告

基线：`main` 34c645b；实施分支：`fix/remaining-1.3.1`。仅在隔离临时数据库、合成联系人和 mock 模型/邮箱下验证。没有调用真实模型、连接收件箱、发信或部署。

## P1–P12 状态

| 项 | 状态 | 结果 |
| --- | --- | --- |
| P1 回复 Amazon 链接 | 完成 | 回复生成和审核上下文含固定 `BOOK_URL`；首封上下文不含 URL；硬校验拒绝其他链接。 |
| P2 人工接管 | 完成 | 登录/CSRF/双确认入口；原 AI 草稿与审核保留为 `superseded`；新建人工回复并审计。退订、旧来信、收件人不符、发送已尝试和 `uncertain` 均受阻。 |
| P3 质量门槛 | 完成 | 四项越高越好；单项与均值门槛可配。低分记 `quality_below_floor`，首封及分阶段回复最多定向改写一次，旧审核在发送前重新套用门槛。 |
| P4 分阶段自动回复 | 完成 | `process_inbound` 建立持久 job；分类、撰写、审核每 Worker 周期各一次模型调用；阶段前重查新来信与绑定。 |
| P5 研究国家范围 | 完成 | 默认仅 US；配置所选国家轮转，研究提示只列所选国家；候选页可确认后归档范围外待核对象。 |
| P6 KU 到期 | 完成 | 按配置时区与截止日期动态生成书籍事实；过期文案硬拒绝，跨日书籍绑定变化使旧草稿 held。 |
| P7 Profile 启用检查 | 完成 | 发送、研究、自动回复分别检查实际任务路由的协议、HTTPS 端点、模型与密钥，并指出任务名。 |
| P8 Legacy 更新 | 完成 | 分类模型改动只更新分类兼容 Profile/路由；其他全局字段按受影响字段更新，保留无关 effort、token 预算和 secret_ref。 |
| P9 资格统计 | 完成 | 列表、详情、统计共用含 `permission_note` 的资格查询字段。 |
| P10 只读报告 | 完成 | `qualification-report` 用 SQLite 只读模式输出资格、原因、国家、待核上限与当日用量，不输出联系人信息。 |
| P11 文档 | 完成 | README 首信/三模式说明、配置与人工接管；CHANGELOG、生成合同与升级回退说明同步更新。 |
| P12 隐私检查 | 完成 | `git log --all -p -- resources/history.json`：历史文件内容含真实联系人邮箱：**无**；涉及提交：**无**。提交作者地址不计入文件内容。未改写历史。 |

## 改动文件

- 核心：`outreach/ai.py`、`contracts.py`、`domain.py`、`generation.py`、`pipeline.py`、`engine.py`、`worker.py`、`profiles.py`、`settings.py`、`composition.py`、`db.py`、新增 `migration5.py`、`cli.py`。
- 界面：`outreach/web.py`、`outreach/templates/message.html`、`contacts.html`。
- 版本与运维：`VERSION`、`outreach/__init__.py`、`compose.yaml`、`deploy/upgrade.sh`、`deploy/rollback.py`、`tools/package_release.py`。
- 文档：`README_部署与使用.md`、`docs/EMAIL_GENERATION.md`、`docs/CHANGELOG.md`、`docs/UPGRADE_ROLLBACK_1.3.md`、本报告。
- 测试：新增 `tests/test_remaining_131.py`；调整 `test_ai_review_send.py`、`test_candidate_qualification.py`、`test_mail_engine.py`、`test_network_ai.py`、`test_upgrade_contract.py`、`test_v11_boundaries.py`、`test_v11_final_review.py`、`test_v11_upgrade_script.py`、`test_v12_review.py`、`test_web.py`、`test_worker_flow.py`。

## 新增测试

`test_reply_context_has_only_reply_amazon_link`、`test_manual_takeover_preserves_ai_and_sensitive_reply`、`test_manual_takeover_stops_on_optout_and_new_inbound`、`test_quality_floor_scores_and_single_rewrite`、`test_reply_worker_stages_allow_three_virtual_35_second_calls`、`test_new_inbound_stops_reply_between_stages`、`test_reply_quality_rewrites_once_then_holds`、`test_country_rotation_default_and_selected`、`test_ku_date_and_hard_guard`、`test_ku_expiry_invalidates_queued_draft`、`test_profiles_and_legacy_classification_edit`、`test_profile_readiness_uses_task_keys_without_global_key`、`test_qualification_report_never_emits_email`、`test_schema4_to5_pauses_and_preserves_reply_history`、`test_schema4_backup_can_rollback_offline_without_enabling`；另在 `test_web.py` 新增范围外归档、consent 资格一致性、人工接管 CSRF/双确认及按路由启用四项测试。

## 旧测试调整

- `test_candidate_qualification.py`、`test_network_ai.py`：13 国轮转测试显式选中 13 国；默认现在仅 US，保留多国能力和资格断言。
- `test_ai_review_send.py`：补齐合成来信 sender，与新的收件身份硬校验一致。
- `test_upgrade_contract.py`、`test_v11_boundaries.py`、`test_v11_final_review.py`、`test_v12_review.py`：迁移目标版本由 schema4 改为 schema5；原“AI 草稿不可人工改标”断言改为检查显式接管后两份独立记录和原审核保留。
- `test_mail_engine.py`、`test_v11_final_review.py`、`test_worker_flow.py`：按持久阶段驱动 Worker 周期；原同步处理的分类/回复结果断言仍保留。
- `test_v11_upgrade_script.py`：目标版本改为 1.3.1，增加 1.3.0 作为受支持旧版；备份失败与不删卷断言仍保留。
- `test_web.py`：健康检查版本改为 1.3.1。

## 验证与上线边界

- 本地命令：`python -m pytest -q`：308 passed、0 failed、1 条 Starlette 依赖弃用警告；`python -m compileall -q outreach`：通过；`git diff --check`：通过。
- schema4→5 迁移保留原记录、凭证、抑制、UID 和发送计数；关闭全部自动化，未发草稿 held，未决发送 uncertain。回退须用迁移前私有备份恢复到新空目录，绝不能用旧程序打开 schema5。
- 仍需另行授权并在真实环境核对：真实模型与网关的 Profile/参数及预算、SMTP/IMAP 验证和投递、Docker 1.3.0→1.3.1 升级/回退、Tailscale 绑定与时区跨日运行。mock 测试不证明这些真实服务可用。

# Markdown文档复核

2026-09-26，候选池2000变更，基线main `2a727207fc9b582b80091f98d85b968e0eff6656`。

检查工作树内所有Git跟踪及未忽略Markdown。当前操作文档按源码、配置默认值、Compose与部署脚本复核；历史文档保留原始记录并添加醒目标识，不把历史测试、限制或部署状态写成今天的事实。

主要修正：Git安装取代旧ZIP步骤；移除预置真实联系人说明；首信分阶段生成与全模式独立审核；默认US与13国可选；2000人活跃池和每日10封的区别；三种来信处理、回复预算与限次；KU开始/截止日期；实际页脚；六任务Profile；schema5与旧升级脚本仅支持目标1.3.1的限制。新增其他领域扩展指南，明确目前产品事实仍在代码中绑定，尚无多活动平台。

离线检查命令：`python3 tools/check_docs.py`。检查相对文件链接、代码围栏、空文件和若干凭证字面量格式。外部URL未联网验证，标题锚点未检查，扫描不是Git历史或全面隐私审计。历史文件中的旧数值有意保留；未声称其全部适用于当前代码。

当前回归：338 passed，0 failed；无真实模型/邮箱测试。完整证据边界见[测试报告](TEST_REPORT.md)。

## 文件清单

| 文件 | 处理 |
|---|---|
| `AGENTS.md` | 当前文档，复核 |
| `README.md` | 当前文档，复核 |
| `README_部署与使用.md` | 当前文档，复核 |
| `docs/ACCEPTANCE_1.3.md` | 历史记录，保留并标识 |
| `docs/CANDIDATE_ARCHIVAL_DELIVERY.md` | 历史记录，保留并标识 |
| `docs/CANDIDATE_ARCHIVAL_PLAN.md` | 历史记录，保留并标识 |
| `docs/CANDIDATE_POOL_2000.md` | 当前文档，复核 |
| `docs/CANDIDATE_QUALIFICATION_IMPLEMENTATION.md` | 历史记录，保留并标识 |
| `docs/CHANGELOG.md` | 当前文档，复核 |
| `docs/CODEX_BOOK_MKT_UPGRADE.md` | 阶段性需求，保留并标识 |
| `docs/CONTINUOUS_REPLY_TRIAGE.md` | 当前文档，复核 |
| `docs/DEPLOYMENT_1.3.1.md` | 历史记录，保留并标识 |
| `docs/DEPLOYMENT_1.3.md` | 历史记录，保留并标识 |
| `docs/DESIGN.md` | 当前文档，复核 |
| `docs/DOCUMENTATION_AUDIT.md` | 当前文档，复核 |
| `docs/EDITORIAL_PREVIEW_PLAN.md` | 历史记录，保留并标识 |
| `docs/EMAIL_GENERATION.md` | 当前文档，复核 |
| `docs/EXTENDING_TO_OTHER_DOMAINS.md` | 当前文档，复核 |
| `docs/FIX_REPORT_1.3.1.md` | 历史记录，保留并标识 |
| `docs/IMPLEMENTATION_PLAN.md` | 历史记录，保留并标识 |
| `docs/INDEX.md` | 当前文档，复核 |
| `docs/LIVE_GENERATION_CHECK_20260925.md` | 历史记录，保留并标识 |
| `docs/MARKETING_SCHEDULER_1.3.md` | 历史记录，保留并标识 |
| `docs/MODEL_ROUTING.md` | 当前文档，复核 |
| `docs/PLAN_v1.2.md` | 历史记录，保留并标识 |
| `docs/PROMPT_CANDIDATE_QUALIFICATION_OPTIMIZATION.md` | 阶段性需求，保留并标识 |
| `docs/REPOSITORY_REVIEW.md` | 历史记录，保留并标识 |
| `docs/REVIEW_FEEDBACK.md` | 历史记录，保留并标识 |
| `docs/REVIEW_FEEDBACK_v1.2.md` | 历史记录，保留并标识 |
| `docs/STATUS.md` | 当前文档，复核 |
| `docs/TEST_REPORT.md` | 当前文档，复核 |
| `docs/UPGRADE_IMPLEMENTATION_PLAN.md` | 历史记录，保留并标识 |
| `docs/UPGRADE_ROLLBACK_1.3.md` | 当前文档，复核 |
| `docs/history_v1.0/CHANGELOG.md` | 历史记录，保留并标识 |
| `docs/history_v1.0/DESIGN.md` | 历史记录，保留并标识 |
| `docs/history_v1.0/IMPLEMENTATION_PLAN.md` | 历史记录，保留并标识 |
| `docs/history_v1.0/README.md` | 历史记录，保留并标识 |
| `docs/history_v1.0/TEST_REPORT.md` | 历史记录，保留并标识 |
| `docs/history_v1.1/AGENTS.md` | 历史记录，保留并标识 |
| `docs/history_v1.1/CHANGELOG.md` | 历史记录，保留并标识 |
| `docs/history_v1.1/DESIGN.md` | 历史记录，保留并标识 |
| `docs/history_v1.1/IMPLEMENTATION_PLAN.md` | 历史记录，保留并标识 |
| `docs/history_v1.1/README_部署与使用.md` | 历史记录，保留并标识 |
| `docs/history_v1.1/REVIEW_FEEDBACK.md` | 历史记录，保留并标识 |
| `docs/history_v1.1/TEST_REPORT.md` | 历史记录，保留并标识 |
| `docs/history_v1.2/DESIGN.md` | 历史记录，保留并标识 |
| `docs/history_v1.2/TEST_REPORT.md` | 历史记录，保留并标识 |
| `docs/上线前真实服务验收.md` | 当前文档，复核 |
| `docs/升级与回退_v1.1.md` | 历史记录，保留并标识 |
| `docs/升级与回退_v1.2.md` | 历史记录，保留并标识 |
| `docs/原生Debian部署.md` | 当前文档，复核 |
| `docs/合规与安全边界.md` | 当前文档，复核 |
| `docs/首封邮件示例_v1.2.md` | 历史记录，保留并标识 |

检查结果：53份Markdown、99处相对文件链接，0项错误。

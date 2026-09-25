# Reader Studio v1.2 — review-driven patch plan

Baseline: delivered v1.1 archive (SHA-256 7865a15ba65891bd0897d04e2b93ea6099a3045f87059f9da710e226fa637781). Scope: evaluate and implement the user's supplied review; not a new product or a strategy change.

- [x] Reproduce geography rejection, generic composition and unsupported provider option; record old test baseline.
- [x] Fresh installations: America/New_York 08:30–19:30, 70-minute gap. Existing schedules remain unchanged on migration; show warning and an explicit paused preset action. Persist schema3 migration, disable automation, preserve credentials/history/UID/counters and hold old pending work.
- [x] Parse source-supported city+state/ZIP or explicit US-based wording. State abbreviations must be uppercase. Do not infer Chicago-only locations, citizenship, consent or location from client lists/negative/former/foreign-context assertions. Record decision details. Require v3 source evidence for autonomous public-US outreach.
- [x] Compose concise initial copy with a source-proven quote/topic, a model-selected natural opening/subject form, the complete title/author/Amazon statement, one persona-specific benefit and Think → Write → Build → Check. No free-form invented achievements. Max120 words excluding compliance footer, no links or requests for reviews. At most2 generation attempts. Keep a valid deterministic fallback only for documented consent without evidence.
- [x] Brave: follow at most2 observed Contact/About/Team links per landing page, same HTTPS origin, no guessed paths/no cross-site crawl/no query URLs; respect robots/refusal notices and shared daily fetch budget. Reject an owner group when refusal is observed on any visited page.
- [x] Anthropic: basic native web_search_20250305 with bounded uses, actual server_tool_use/result proof and sources, explicit error handling and at most2 pause_turn continuations with unmodified content and per-request budget/use logs. Chat mode remains Brave-only. No assumed model/account capability.
- [x] Refactor only touched logic for readability; retain unrelated scheduling/mail transport code.
- [x] Unit/HTTP adapter/integration/migration tests; desktop/mobile rendering; code/shell/ZIP checks. No external model requests, credentials or email sending. Package separate v1.2 with upgrade and rollback docs.

Review focus: overlapping source quotes; country evidence in client/event/history sentences; hostile Contact links/refusal pages; incomplete native search with successful HTTP; timezone changes resetting daily counters; migration leaving old queued invitations eligible.

## 完成边界

本地188项测试、跨版本迁移、原生进程和18次页面内容渲染已执行。浏览器对本地URL访问被环境拒绝，未绕过；不声称完整浏览器交互、Docker或真实SMTP/IMAP/API服务通过。封装后复测记录在独立发布检查文件。

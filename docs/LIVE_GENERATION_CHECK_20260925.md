> **历史或阶段性记录，非当前操作指南。** 本文的版本、上限、命令、测试与部署状态只对应原记录阶段；保留原文供追溯。当前1.3.2/schema5、2000人候选池及操作方法见[部署与使用](../README_部署与使用.md)。

# Authorized live generation check — 2026-09-25

The owner authorized real verification of configured model access, source reverification, generation and review. Sending, automatic replies and scheduled research remained disabled throughout. No SMTP delivery was requested or performed.

- The explicitly configured shared key works with the existing `claude-sonnet-5` profile over Responses. The connection test returned valid JSON and the gateway reported that model. This does not independently prove upstream identity or effective reasoning effort.
- Source reverification fetched the existing contact's public source, passed eligibility checks and stored an active literal evidence snapshot.
- The configured `gpt-6-luna` brief stage initially returned invalid literal evidence references. The evidence validator rejected them. Prompt instructions now spell out exact snapshot IDs, contiguous literal quotes, types and length bounds; no validators were relaxed.
- A subsequent Worker job completed the brief and Sonnet composition stages, persisted a new draft revision and invoked independent Sonnet review.
- Review rejected an unsupported characterization of the recipient's work. The automatic revision attempt then exceeded the existing 100-second chain deadline. The job terminated and the draft remained held. This is **not** a successful approved-draft acceptance test.
- An authenticated GET of the deployed message page returned HTTP 200 and contained the current subject, body and failure notice. No page content or recipient data is included here.
- Accepted outbound count was unchanged. Health endpoint and Worker remained operational.

Related fixes include separating the Worker job record from the message record during redraft, explicit missing-evidence guidance and clearer per-profile credential instructions. The full isolated suite passed 258 tests before the prompt clarification; the affected suite passed 53 tests after it (one third-party deprecation warning). Tests use synthetic fixtures and do not substitute for the live results above.

Remaining limitation: multi-stage generation with slow models can exhaust the bounded chain, especially after a review rejection. No provider/model downgrade, timeout-limit relaxation or automatic repeated paid retry was applied. Live reply generation and SMTP delivery were not tested.

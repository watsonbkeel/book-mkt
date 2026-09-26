# Model routing (1.3)

Six explicit routes: research, brief, compose, review, classification, reply. Profile holds protocol, HTTPS443 base URL, model ID, encrypted secret reference, effort/thinking, token budget (256–16000), timeout (5–90s), declared native-search capability and administrator capability status. Configure at `/profiles`; the old settings edit the explicit Legacy compatibility profiles. Existing classification model override is retained. Legacy research retains the old 5500-token budget, other Legacy tasks retain 2200. No vendor/model auto-selection, downgrade or fallback.

| Protocol | Effort payload | Thinking | Output budget |
|---|---|---|---|
| Responses | `reasoning: {effort: ...}` | not applicable | `max_output_tokens` |
| Chat Completions | `reasoning_effort: ...` | not applicable | `max_completion_tokens` |
| Anthropic Messages | `output_config: {effort: ...}` | explicit `thinking.type` omit/adaptive/enabled/disabled; enabled includes `budget_tokens` smaller than max_tokens | `max_tokens` |

`default` / `omit` omit effort; `none` explicitly sends a value (not supported by this Messages adapter). Model/endpoint capabilities differ. Unsupported declared effort is rejected; unknown gateway capability stays **unverified** while the exact chosen parameter is transmitted. `max` is never rewritten to `high`. An administrator's declaration is not evidence that the provider adopted a parameter.

Luna medium for research/brief, Luna low/medium for classification, and Sonnet high for compose/reply are candidate configurations **for administrator confirmation**, not installed routes. Enter the exact model IDs and protocols available in the actual account; single-model Legacy compatibility is supported. An unconfigured key/model fails closed.

Changing endpoint or protocol requires explicitly supplying a new key. No inherited key is forwarded to a new host. Keys stay encrypted in the existing secrets table. DNS pinning/SSRF/HTTPS443 checks apply at request time. No native tools are sent to compose/review/classification/reply. Responses native search, Anthropic matching tool results/pause_turn, and Brave owner-page extraction remain in the research path. Brave extraction routes to research without native tools.

Every request, failed attempt, revision, review and Messages continuation is logged. Marketing and research requests count against their configured budgets; classification, reply and reply_review calls have no application daily model-call cap and do not consume the marketing allowance. Mail frequency, thread limits and provider quotas still apply. Each generation stage/tick is bounded to 100s and 10 model requests; initial and reply pipelines persist stages and perform one model call per stage; each network timeout is capped by remaining time. Worker SIGALRM enforces wall time on the main thread; graceful stop prevents subsequent dispatch. No budget increase is made by a migration.

`api_usage.details` stores task, draft ID, profile version, requested/reported model, requested/sent parameters, actual timeout, output budget, request/prompt/material hashes, elapsed time and finish status. Existing token fields record usage. No keys, request headers or raw thinking blocks are logged. The UI distinguishes parameters_sent, http_success and provider_confirmed; provider adoption remains false/unknown unless explicitly supported by an upstream report (the current adapters do not claim adoption from HTTP success).

Parameter preview is local. Explicit profile test requires a checked fee confirmation and schedules a Worker job. No test is run by saving a profile. Profile/route changes visibly hold old drafts. All draft bindings include profile versions so stale reviews cannot authorize sends.

Protocol references: https://developers.openai.com/api/docs/guides/reasoning and https://platform.openai.com/docs/guides/reasoning (retrieval returned HTTP403 in this environment; no current model capability claim); https://platform.claude.com/docs/en/build-with-claude/adaptive-thinking (HTTP200 redirected to an unavailable-in-region page; current protocol content could not be verified). Payload shape is tested with captured mock requests; this historical reference retrieval did not verify gateway/model access. Subsequent authorized live preview calls are recorded in TEST_REPORT.md, and still do not prove provider adoption of optional parameters.

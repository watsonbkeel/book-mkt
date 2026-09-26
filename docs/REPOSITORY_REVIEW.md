> **历史或阶段性记录，非当前操作指南。** 本文的版本、上限、命令、测试与部署状态只对应原记录阶段；保留原文供追溯。当前1.3.2/schema5、2000人候选池及操作方法见[部署与使用](../README_部署与使用.md)。

# book-mkt仓库复核：上一版Codex指令的必要调整

日期：2026-09-25  
审阅对象：watsonbkeel/book-mkt，main，commit `a58f0467d680f09572f929cec3757ffd189e9ed9`。  
方法：通过GitHub连接读取固定commit的源文件、仓库约束、部署脚本和相关测试，与上一版完整Codex执行规格比较。

## 结论

旧指令的目标仍成立：完整模型写作、分任务模型路由、参数真实传递、兑现首封承诺。但不能原封不动当成针对原私有v1.2 ZIP的任务执行。当前仓库已经增加AI审核和研究扩展，公开数据边界也不同。

应使用同目录的 `CODEX_BOOK_MKT_UPGRADE.md` 整体替换旧规格。不要将两份同时当作当前指令；也不要把新规格理解成代码已经修改。

## 已核实事实和具体调整

| 项目 | 代码事实 | 对开发指令的修改 |
|---|---|---|
| 固定正文仍在 | composition.render_initial固定拼接书介、BENEFITS、邀请和KU；AI.initial_copy只选四个槽位 | 完整subject/body改造仍然必须做；不是只换模型 |
| 根AGENTS冲突 | AGENTS要求完整副标题与literal source quote/topic＋patterns | 明确授权替换这两项旧文案契约，并同步当前文档、验证器与测试；其他安全边界保留 |
| 已有AI审核 | AI.review_initial/review_reply、Engine.review_initial/queue_reply、tests/test_ai_review_send.py已存在 | 不再从零造第二套审核；将完整新草稿接入并版本化现有审核 |
| 三种模式 | settings支持review、ai_review、automatic；automatic直接入队，dispatch只在ai_review验证AI哈希 | 新设计须明确三模式含义：都不能绕过新AI草稿硬检查与质量审核；人工模式另加人工确认 |
| 旧渲染耦合 | Engine.review_initial要求body==render_initial(contact,copy) | 写作接口、草稿证据、审核、编辑、批准、发送一起变更，否则新正文会被旧相等性判定挡住 |
| 证据不够不只是切片 | research.verify_candidate只保存短fit_quote、邮箱附近文本及不含text的网页元数据；写作/审核再切1000字符 | 在研究阶段保存受限原文快照，旧候选明确补齐；不把bio/fit_reason冒充证据 |
| 研究已扩展 | TARGET_COUNTRIES13国；包含技术实践者及儿童AI教育相关成年教育者；非US许可门槛仍在 | 保留研究范围、轮换、周期配置与成年边界，不变成只搜美国，也不放开全球无许可发送 |
| 模型缺口仍在 | 同端点密钥；仅分类模型名可另配；Anthropic无effort/thinking；一般2200、研究5500、json timeout90 | 独立profiles及任务映射仍必需；保留原生搜索；参数请求mock测试、预算和超时分任务 |
| 错误写进许可 | Worker.tick草稿异常覆盖permission_note；Engine.eligible的consent分支仅用bool(permission_note) | 修复错误字段污染；失败不覆盖真实许可、不因错误非空制造许可；缺证据旧记录转人工 |
| 高推理与调度 | Worker.tick同步串行，Compose停机宽限120s；小时轮询/75min健康已存在 | 对慢调用、链总时限、取消、重启加测试，不能靠高频收信或放宽健康掩盖问题 |
| 公开历史已清空 | resources/history.json的contacts=[]，README说明public release不包含私有运营数据 | 删除“必须保留原包12人名单”的发行要求；真实历史留在运行数据库，禁止从旧私有包或聊天补回public repo |
| schema与部署 | db schema3；upgrade脚本只接受1.0/1.1→1.2；compose已有WEB_BIND_IP/WEB_PORT | 新迁移必须覆盖当前1.2/schema3；保留Tailscale/端口/卷/.env；不要原样复用旧升级脚本 |
| 测试基线 | docs/TEST_REPORT.md仍为旧188测试报告，另有新增审核测试 | 要求Codex重新运行当前HEAD，不以旧报告数字替代实测 |

## 关键源码入口（均固定到审阅commit）

- [AGENTS.md](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/AGENTS.md)
- [README.md](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/README.md)
- [composition.py](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/outreach/composition.py)
- [ai.py](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/outreach/ai.py)
- [engine.py](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/outreach/engine.py)
- [web.py](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/outreach/web.py)
- [research.py](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/outreach/research.py)
- [settings.py](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/outreach/settings.py)
- [anthropic_search.py](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/outreach/anthropic_search.py)
- [net.py](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/outreach/net.py)
- [worker.py](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/outreach/worker.py)
- [domain.py](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/outreach/domain.py)
- [db.py](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/outreach/db.py)
- [compose.yaml](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/compose.yaml)
- [deploy/upgrade.sh](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/deploy/upgrade.sh)
- [resources/history.json](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/resources/history.json)
- [tests/test_ai_review_send.py](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/tests/test_ai_review_send.py)
- [docs/DESIGN.md](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/docs/DESIGN.md)
- [docs/TEST_REPORT.md](https://github.com/watsonbkeel/book-mkt/blob/a58f0467d680f09572f929cec3757ffd189e9ed9/docs/TEST_REPORT.md)

## 边界

- 本轮是远程静态源码审阅和开发指令修订，没有修改GitHub文件、创建分支或提交。
- 本环境git clone因DNS解析失败，未取得可执行的完整当前仓库副本；没有运行当前仓库全部pytest。旧附件的测试结果不能代替这次仓库回归。
- 所列错误字段写入和分支行为来自实际源码，不是声称已经在生产环境重现。
- 没有调用真实模型/SMTP/IMAP或读取用户生产数据库；没有验证某型号或网关权限/推理效果。
- 只确认公开history资源为空，不据此宣布做过完整秘密或隐私扫描；规格要求发行前另做扫描。
- 新规格的字段、模式语义和验收测试是建议的开发目标，不是当前系统已具备的功能。

## 外部协议依据（仅用于参数约束，不覆盖仓库事实）

OpenAI reasoning guide：https://developers.openai.com/api/docs/guides/reasoning  
支持effort值及默认值依模型而异；推理预算与可见正文预算要一起考虑。实施时重查对应供应商官方文档和实际网关能力，不用模型别名推断所有协议字段都受支持。

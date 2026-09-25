# Reader Studio v1.2 — 实际验证报告

日期：2026-09-24。基线：用户提供的v1.1 ZIP（指纹见`evidence_v1.2/environment_and_preservation.json`）。本报告只包含实际完成的本地验证，不包含线上邮件送达、搜索产出率或法律结论。

## 本轮结果

| 检查 | 实际结果 | 记录 |
|---|---|---|
| 未修改v1.1基线 | 119 passed | evidence_v1.2/baseline-v11.txt |
| 新版完整测试 | **188 passed，0 failed** | evidence_v1.2/pytest-final.txt、pytest-results.xml |
| Python编译 | outreach与tests通过 | environment_and_preservation.json |
| Shell脚本语法 | deploy与tools下所有.sh通过 | environment_and_preservation.json |
| Compose静态结构 | 私有端口、项目/卷保留、image1.2.0 | environment_and_preservation.json；不等于容器构建运行 |
| 实际旧v1.1进程建库→新代码迁移 | schema2→3；原时区/自定gap、密文/key、14项夹具记录（12历史+2虚构）、停发及UID保持 | runtime_and_ui.json |
| 新版备份/恢复 | 新空目录可恢复、14项夹具记录保持、自动化关闭 | runtime_and_ui.json |
| 旧代码碰新schema | 对副本测试旧v1.1明确拒绝schema3 | runtime_and_ui.json |
| 新版原生进程 | Uvicorn health1.2.0、独立Worker心跳/STATUS正常、第二worker被锁拒绝 | runtime_and_ui.json |
| 默认运行零外发 | 无IMAP/SMTP/API凭证；native隔离库messages=0、api_usage=0，全部自动化OFF | runtime_and_ui.json |
| Web HTTP操作 | FastAPI TestClient登录、CSRF、设置与预设确认、草稿/线程等测试通过 | pytest-results.xml |
| 浏览器内容渲染 | 9页×1440/390px＝18次，无页面横向溢出 | runtime_and_ui.json、ui-*.png |
| 目视检查 | 已查看桌面总览、长设置页、邮件详情与手机总览，演示数据明确标注 | 对应ui截图 |
| 12人历史/18章目录/依赖文件 | 与v1.1逐字节一致 | environment_and_preservation.json |

## 主要测试覆盖

- 新装NY08:30–19:30、gap70理论容量10；夏令时/冬令时边界；旧HK时区包括缺字段旧配置均保留；明确点击预设暂停，保留较低daily_limit和密钥。
- 单页面城市+州、州+ZIP、US-based；大小写与长州名、DC；不存在的摘录、跨页拼句、只写Chicago/Portland、客户/曾居/活动/否定/国外冲突都待核实。
- 最后防御回归发现workshops复数、Perth WA、Tbilisi Georgia歧义误放行，先写3个失败用例后修复；不把此词法检查冒充完整全球地理认证。
- 原验证版本2不能自动继续发；升级保持旧正文/消息ID/时间、暂停、held/uncertain，不重复执行迁移。
- 来源quote/topic逐字匹配、受控自然开场/动态subject、三类读者价值、四步法、完整书名/作者/Amazon、<=120词。模型捏造、链接/控制字符或超长度被拒；最多两次。主题不得假冒Re:/Fwd:已有会话；实际发送前再检查。
- Brave跟随实际同站Contact/About/Team链接；跨站/非HTTPS/query/重复/猜测路径不跟随；拒收页面使已读取的同站来源不进入提取；fetch预算耗尽不会隐藏并继续请求。
- Anthropic基础server_tool_use/result、HTTP200错误对象、缺结果/客户端工具拒绝；pause_turn原样回传encrypted_content；最长2次续接，搜索总上限4，每个请求消耗模型预算，Token与状态按请求记录。未测试真实网关。
- v1.1小时收信、发送限额、同域冷却、SMTP各状态/未知不重试、退订、投诉/硬退信暂停、自动通知/附件边界、线程/DMARC、登录/加密/恢复等既有保护继续回归。
- 升级脚本旧VERSION矩阵包含1.0.0/1.1.0及成功/备份导出失败；使用假docker程序观察命令编排，失败不启动、不删卷。

## 测试过程与原测试修改说明

先执行新增测试时为31失败/22通过；首次53个新测试修复后通过。又加14个防御/HTTP整合用例，3个地点用例先失败后修复。旧测试仅调整新schema/验证版本、个性化适配器契约和明确固定旧HK窗口的计时夹具；没有移除邮件安全断言。总计188项：原119覆盖更新后保留，新67项，旧升级脚本矩阵再增加2种组合。

红阶段/中间失败日志在evidence_v1.2里作为过程保留，不能覆盖最终pytest-final.txt结论。旧v1.1报告原样保存在history_v1.1，不能作为本版验证。

## 未完成／部署后必须验收

1. **Docker**：本环境没有docker命令/引擎，未执行镜像构建、Debian实机Compose启动。
2. **浏览器整站交互**：实际Chromium导航到本地HTTP返回ERR_BLOCKED_BY_ADMINISTRATOR。未绕过限制；TestClient做HTTP操作，Chromium只渲染已取得且内联CSS的HTML，两者不等同真实浏览器端到端。
3. **真实外部服务**：没有使用真实邮箱、API Key、MX/SMTP/IMAP或模型/搜索账号发送请求。接口与来源检查使用明确标注的本地夹具；网站研究能力/真实网关native工具权限/费用仍未验收。
4. **送达与读者**：无真实邮件发送、订单、KENP、阅读开始、评论、转化率或域名信誉验证。界面截图包含虚构测试数据，不是用户当前推广统计。
5. **独立审计**：本轮是源码自审与测试，没有第二模型/外部安全审计。

使用`上线前真实服务验收.md`在自己的测试邮箱完成闭环后再启用。包中无运行数据库、主密钥、备份或真实凭证；历史业务邮箱资料仅供本私有项目去重使用。

## 本地复现命令

```bash
python -m pytest -q
python -m compileall -q outreach tests
bash -n deploy/*.sh tools/*.sh
# 可选界面/原生/迁移复查：另需playwright和本机Chromium（生产部署不需要安装）
python tools/verify_local_runtime.py --baseline /已解压的原版1.1目录 --chromium /usr/bin/chromium
```

可选脚本在TemporaryDirectory中生成测试密钥和夹具，不使用服务器生产OUTREACH_DATA_DIR，不调用SMTP/IMAP/模型。它会写本地检查报告/截图，但不会改变生产数据。

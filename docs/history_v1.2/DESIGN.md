# Reader Studio v1.2 — 审阅驱动的局部改版

## 本轮依据与范围
用户要求核对v1.1外部审阅、修正美国时区、所在地证据和首封表达，并评估原生Anthropic搜索与Contact页产出。以实际v1.1源码和119项基线测试为依据，不把外部给出的“上线可用”和“所有候选都卡住”当成已经测得的事实。

保留FastAPI/Jinja2、SQLite WAL、独立单Worker和SMTP/IMAP。每天最多10封首封，默认70分钟（最小61），收信固定3600秒、失败不加速，75分钟健康检查，退订/退信/投诉自动停发、默认暂停和审核模式均不变。书价、Select、Amazon页面、广告与全书定位不改。

## 组件与接口
- `location.evaluate_us_location(quote, page_texts)`返回status/rule/reason/quote；程序验证单页真实片段、城市+州或明确US声明，以及上下文冲突。不做外部地理定位、不推断国籍/法律许可。`research.verify_candidate`保留邮箱、所有者域、姓名、活动、MX、拒收与联系范围核验，证据版本3。
- `composition.validate_copy_slots(contact, result)`验证模型的quote/topic/表达样式；`render_initial`由程序加入书名、作者、Amazon、四步法和画像价值句。标题有三类自然形式，以来源主题个性化；不是任意自由写信。最多两次模型尝试，主体不超过120词；合规页脚独立追加。缺来源时仅有已记录真实许可的联系人使用无事实声称的回退。
- `SourceFetcher.fetch`额外返回实际同站Contact/About/Team链接；`AI._fetch_owner_pages`每轮最多6个落地页、每页最多2个关联链接，深度一层，共用fetch预算。robots/禁止采集与推销规则不弱化。
- `anthropic_search.messages_call`提供基本原生server web search；最多4次搜索、2次pause_turn续接，完整传回原始content，不执行客户端工具。实际调用与结果一一对应，错误对象/截断/超预算失败；每次请求记录token与用途。模型名称自由配置，工具可用性须实际账号测试。
- `Config.apply_us_schedule`仅由已登录、有CSRF和明确确认的管理操作使用：America/New_York、08:30–19:30、gap70并关闭全部自动化。新装直接采用这些值，旧库迁移保留原值，不能默默改变原任务的当地日期边界。

## 数据版本与上线
schema1/2 → 3：保留密文、key、历史、真实Message-ID/MIME、UID、停发名单和每日实际时间；暂停全部自动化，旧draft/queued→held、sending→uncertain，旧任务不重跑。旧公开来源版本重新核验至v3后才能自动排队；有许可路径不伪造新来源。重复初始化schema3不会再次暂停，回退必须恢复升级前备份到空卷。

部署仍为单管理员、单邮箱、同名Compose卷，默认127.0.0.1绑定。不新增云端数据同步，STATUS只在服务器生成。真实服务验收必须在本人控制的测试邮箱进行，不把夹具测试变成实际送达/转化证据。

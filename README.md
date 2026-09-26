# Book Marketing — 有证据的读者拓展与邮件回复

当前应用版本 **1.3.2 / schema 5**。单机、单管理员、单邮箱、单 Worker，使用 FastAPI、SQLite 与 Docker Compose。当前推广对象固定为 Huashan Chen 的英文书 **Use AI to Direct AI**；它不是开箱即用的通用群发平台。

系统从公开来源寻找成年读者，保存证据快照，生成客户简报，再由模型完整撰写主题和正文。独立模型审核与程序硬校验通过后进入现有审核/发送队列。收到回复后选择停止联系、自动回复或人工处理。它不依赖当前 ChatGPT 会话持续打开。

## 从这里开始

| 你要做什么 | 阅读入口 |
|---|---|
| 安装、配置服务、启用与日常运维 | [部署与使用](README_部署与使用.md) |
| 了解模型路由、参数和费用边界 | [模型 Profile](docs/MODEL_ROUTING.md) |
| 理解文案、证据、审核和首信承诺 | [邮件生成](docs/EMAIL_GENERATION.md) |
| 持续运行与三种来信处理 | [来信处理](docs/CONTINUOUS_REPLY_TRIAGE.md) |
| 积累最多 2000 名活跃候选 | [候选池](docs/CANDIDATE_POOL_2000.md) |
| 升级、备份与回退 | [当前升级指南](docs/UPGRADE_ROLLBACK_1.3.md) |
| 改为推广另一书籍、产品或服务 | [扩展到其他领域](docs/EXTENDING_TO_OTHER_DOMAINS.md) |
| 查看文档与验证证据 | [文档索引](docs/INDEX.md)、[测试报告](docs/TEST_REPORT.md) |

## 安装概览

准备 Docker Engine、Compose 插件、Git，以及你有权使用的 SMTP/IMAP、模型和搜索服务。新安装步骤：

```bash
git clone https://github.com/watsonbkeel/book-mkt.git
cd book-mkt
bash deploy/setup.sh
```

记录初始化终端显示的管理员随机密码。默认监听服务器 `127.0.0.1:8096`，**研究、发送和自动回复默认关闭**。通过 SSH 隧道访问，或在 `.env` 配置你自己的 Tailscale IP；不要绑定未经保护的公网地址。具体命令、首次启用顺序与健康检查见[部署指南](README_部署与使用.md)。

公开 `resources/history.json` 为空，初始化不导入任何真实联系人。配置和加密密钥在私有数据卷中，不能提交 GitHub。

## 运行行为

- 活跃候选池：待核、可起草和排队合计最多 **2000**。研究按配置周期和预算补充，未发候选证据过期可归档留痕并释放名额。候选不等于具备发送资格。
- 研究国家：默认只选 `US`，可配置所支持的 13 国。研究范围不等于发送许可；其他国家的公开邮箱不会自动获得联系许可。
- 三种审核模式：`review` 需要 AI、程序和人工批准；`ai_review`、`automatic` 都需要 AI 与程序审核。没有免审核模式。
- 首封：模型完整生成，正文 80–120 英文词，不含链接；每日上限 **10**、间隔至少 **61 分钟**（默认 70）。本次候选池扩容没有提高发信限额。
- 来信：明确拒绝如 `Nope` 停止联系且不回复；普通问题由配置的模型生成并审核；敏感、身份不明、审核失败或超出轮次转人工。当前作者部署的分类、回复、审核使用已有 Sonnet Profile；新安装需自行配置，不能凭模型名推断接口能力。
- 收信每小时一次；失败、积压或超过 75 分钟未成功时阻止外发。配置启用后跨重启保存。SMTP 结果 `uncertain` 不自动重发。
- 营销模型调用、研究和网页抓取有预算；分类、回复、回复审核不占营销模型调用额度，但仍有邮件频率、轮次和服务提供方限制。

## 开发与验证

Python 3.13（与 Docker 镜像一致）环境中：

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m compileall -q outreach
```

测试使用临时数据库、合成联系人和 mock。`pytest.ini` 只收集 `tests/`，不读取私有备份。可使用 [离线测试镜像](tools/Dockerfile.offline-tests) 在 `--network none` 容器内运行。

预览与盲评默认使用 mock；真实模型预览必须另行授权费用、指定 Profile 和调用上限，禁止拿生产联系人充当合成样例。SMTP 接受、实际投递、读者阅读与图书订单是不同结果。当前测试、历史真实调用与生产健康检查分别记录在[测试报告](docs/TEST_REPORT.md)中。

## 能否推广其他领域？

可以在现有架构上扩展，但目前书名、目录、Amazon 链接、部分提示词、资格规则和指标仍在代码中绑定本书，**只修改发件人或一句提示词不够**。扩展指南给出可直接配置的部分、必须修改的模块、验证步骤和多活动隔离方案。当前没有多租户、独立活动数据库或通用商品配置 UI，也没有实现更高的每日发送上限。

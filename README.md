# Book Reader Outreach

《Use AI to Direct AI》读者拓展工作台：公开资料搜索、来源核验、AI 文案审核、SMTP 发信及 IMAP 回复处理。

## 部署

详细说明见 [部署与使用](README_部署与使用.md)。需要 Docker Compose：

```bash
bash deploy/setup.sh
```

默认仅绑定 `127.0.0.1:8096`，所有自动化默认关闭。通过管理页面配置邮箱与模型服务，核验后再启用。支持用 `.env` 中的 `WEB_BIND_IP` 绑定自己的 Tailscale 地址。

## 当前功能

- 13 个国家的研究范围，包含科技从业者、创作者和儿童 AI 教育相关的成年教育者。
- 搜索周期可配置；来源引用验证、文案纠错重试、首封与回复的独立 AI 审核。
- 每日首封上限 10 封，默认间隔 70 分钟；收信每小时同步。
- 研究发现与发送资格分开；非美国公开联系人仍需记录联系许可。

## 数据与测试

本仓库不含实际账号配置、联系人、邮件、数据库、主密钥和备份。历史资源为空；测试夹具均为虚构数据。旧版文档保留设计背景，相关私有验收附件不随公开源码发布。

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

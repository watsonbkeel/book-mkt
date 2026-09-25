# Book Reader Outreach 1.3

《Use AI to Direct AI》读者拓展工作台：公开资料搜索、来源核验、AI 文案审核、SMTP 发信及 IMAP 回复处理。

## 部署

详细说明见 [部署与使用](README_部署与使用.md)。需要 Docker Compose：

```bash
bash deploy/setup.sh
```

默认仅绑定 `127.0.0.1:8096`，所有自动化默认关闭。通过管理页面配置邮箱与模型服务，核验后再启用。支持用 `.env` 中的 `WEB_BIND_IP` 绑定自己的 Tailscale 地址。

## 当前功能

完整流程：来源快照 → 客户简报 → 模型完整 subject/body → 独立审核 → 程序硬校验 → 人工批准或排队。review / ai_review / automatic 均检查 AI 草稿；automatic 不跳过审核。模型 ID 和协议由实际 profile 配置，不自动切换供应商。

- [模型配置与参数](docs/MODEL_ROUTING.md)
- [邮件生成与承诺兑现](docs/EMAIL_GENERATION.md)
- [当前 1.2 升级及回退](docs/UPGRADE_ROLLBACK_1.3.md)
- [本地验收与待真实联调项](docs/ACCEPTANCE_1.3.md)

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

## 隔离比较与页面检查

```bash
python tools/blind_compare.py --output /tmp/new-empty-comparison
# 可选真实本地浏览器（不启动 Worker）
python -m pip install playwright
python -m playwright install chromium
python tools/check_upgrade_ui.py --output /tmp/new-empty-ui-check
```

盲评默认 mock、阻断网络、临时数据库；不进入生产队列、不发信。live 比较必须另外授权费用并显式提供 profiles、synthetic 候选编号与调用上限。模型映射另存；mock 输出不能用于比较真实模型效果。

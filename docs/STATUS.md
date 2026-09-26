# 状态说明

当前源码应用版本1.3.2、schema5。此文件是公开文档入口，**不是实时生产统计**，不保存私人联系人、邮件、凭证或备份。

查看实际实例状态：

```bash
docker compose exec -T web python -m outreach.cli status
docker compose exec -T web python -m outreach.cli qualification-report
```

Worker约每小时生成私有数据目录下的 `STATUS.md`。GitHub中的文件不会自动反映服务是否运行、今日发送数量或开关变化。

本地验证见 [TEST_REPORT](TEST_REPORT.md)，功能与用法见 [部署指南](../README_部署与使用.md)，历史记录见 [文档索引](INDEX.md)。

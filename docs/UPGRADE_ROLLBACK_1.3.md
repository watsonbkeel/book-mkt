# 当前部署的升级、备份与回退

适用源码版本 **1.3.2 / schema 5**，默认 Compose 项目 `book-reader-outreach`。执行前确认自己正在操作哪台主机、哪个数据卷和发件账户。新安装见 [部署与使用](../README_部署与使用.md)。

## 1. 先确认脚本适用范围

`deploy/setup.sh` 用于新安装/初始化，不作为升级回退保证。当前 `deploy/upgrade.sh` 的检查写死目标 `VERSION=1.3.1`，来源只接受1.0.0/1.1.0/1.2.0/1.3.0；它**不会升级到当前1.3.2**。保留它用于复现历史版本，不能删除版本校验来强行运行。

`Store.init` 仍支持 schema1/2/3/4→5迁移。迁移保留历史、UID、主密钥、密文、计数与停发；暂停全部自动化，旧未发稿暂缓，未决发送标为uncertain。当前schema5代码更新没有结构迁移；内容/Profile变化仍会使相关旧审核失效。

## 2. 当前版本的受控更新顺序

以下适用于默认 Compose、干净 Git 工作区和本地磁盘卷。存在覆盖文件、自定义项目名或其他同名服务时，先按实际配置调整，不能照抄卷和容器名。

在**更新源码/覆盖镜像之前**：

```bash
git status --short --branch
git rev-parse HEAD
docker compose ps
docker compose exec -T web python -m outreach.cli status
docker inspect book-reader-outreach-web-1 --format '{{.Image}} {{json .Mounts}} {{json .HostConfig.PortBindings}}'
# 暂停外发、研究与回复，随后停Worker以免队列继续执行
docker compose exec -T web python -m outreach.cli pause
docker compose stop worker
# web仍运行，脚本在线快照数据库并复制主密钥
bash deploy/backup.sh
```

保存 `.env`、原先三个开关状态、代码SHA、镜像ID、端口和卷映射到私有运维记录。备份目录必须保持私有，不加入Git。用记录的旧镜像ID创建独立回退标签，例如：

```bash
# 将 OLD_IMAGE_ID 和唯一标签替换成实际值
docker image tag OLD_IMAGE_ID book-reader-outreach:before-update-YYYYMMDD
```

更新、构建和初始化：

```bash
# 要求没有未提交工作；有本地修改时先单独处理
git switch main
git pull --ff-only
docker compose build web
# 共用同一镜像的web/worker均使用此次构建
docker compose stop web
docker compose run --rm --no-deps -T web python -m outreach.cli init
docker compose up -d --no-deps web
docker compose exec -T web python -m outreach.cli status
docker compose up -d worker
docker compose ps
```

构建或备份失败就停止，保留旧镜像和数据。`init` 不附加 `--seed-history`，不重放历史联系人。已有管理员密码不会变化。保持原 `WEB_BIND_IP/WEB_PORT` 和数据卷，包括原 Tailscale IP。

升级验收：核对实际schema、`/health`、两个容器健康、Profile路由、小时收件游标/健康、预算、停发、旧未发稿和uncertain记录。不要直接强制发送来验证部署。已经获得持续运行授权时，检查通过后通过后台恢复此前需要的研究、发送与自动回复；这一步是发布流程的一部分，不应无声留在暂停状态。恢复开关不能绕过缺失配置或收信健康门槛。

## 3. 代码回退（schema保持5）

先暂停自动化并停Worker，备份当前数据库，保留新增SMTP记录。仅在旧镜像与当前schema和状态语义兼容时，使用预留镜像：将旧镜像重新标为compose使用的标签，`docker compose up -d --force-recreate web`，先核对再启动Worker。旧代码不理解新档案/任务/审核规则时，保持自动化关闭直到完成处理。不要用旧数据库覆盖刚产生的发送历史。

## 4. schema回退或灾难恢复

**不对迁移后的schema5数据库执行降级。** 回到旧schema必须停止现有服务，使用对应的升级前备份恢复到新空目录/卷，原数据完整保留。

- `deploy/rollback.sh` 调用离线恢复器，只接受schema1/2/3/4备份且目标目录必须为空；它不迁移数据库、不启动服务，并暂停自动化。
- schema5备份使用当前版本 `outreach.cli restore --input ...`，不是上述旧schema脚本。恢复目标必须是新空数据位置，先用匹配代码核查，恢复会关闭自动化并使旧验证/会话失效。
- 将恢复目录挂载给旧代码前确认文件权限（Docker默认UID/GID10001）、`.env`、端口和卷；只允许一套Worker运行。
- 必须核对备份后发生的SMTP提交、回复、退订与投诉，避免重复联系或复活拒绝者。uncertain不自动重发。

```bash
# 仅示意schema5恢复：目录需全新，使用已安装当前代码的Python环境
OUTREACH_DATA_DIR=/absolute/new-empty-restored-data \
  python -m outreach.cli restore --input /private/outreach-backup.zip
```

禁止 `docker compose down -v` 或删卷来“重新部署”。本文是操作指南，不表示任意主机的真实恢复已经验收；已做与未做的验证分别见 [测试报告](TEST_REPORT.md)。

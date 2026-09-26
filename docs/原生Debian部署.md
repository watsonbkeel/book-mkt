# 原生 Debian + systemd（Compose备选）

优先使用 [Docker部署指南](../README_部署与使用.md)。原生模式只运行一套Web/Worker，不与Compose共用同一运行账户/数据目录。项目容器和本轮测试使用Python3.13；若系统发行版提供不同版本，先在该解释器执行完整测试，不能仅凭版本号声称兼容。

准备好Git、Python解释器、venv、CA证书后，由管理员创建独立系统用户和目录。以下命令假设尚未安装同名用户/服务，执行前先核对：

```bash
sudo useradd --system --home /var/lib/book-reader-outreach --shell /usr/sbin/nologin outreach
sudo git clone https://github.com/watsonbkeel/book-mkt.git /opt/book-reader-outreach
cd /opt/book-reader-outreach
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo install -d -m 700 -o outreach -g outreach /var/lib/book-reader-outreach
sudo -u outreach env OUTREACH_DATA_DIR=/var/lib/book-reader-outreach \
  /opt/book-reader-outreach/.venv/bin/python -m outreach.cli init
# 保存初始化随机密码；不使用--seed-history
sudo cp deploy/outreach-web.service deploy/outreach-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now outreach-web outreach-worker
sudo systemctl status outreach-web outreach-worker
```

默认仅监听127.0.0.1:8096，通过SSH隧道访问。原生service不读取Compose的 `.env`：若需Tailscale绑定，管理员需修改Web service的 `--host` 为本机Tailscale IP，daemon-reload并重启。HTTPS反向代理下修改 `OUTREACH_SECURE_COOKIE=true`；不要将未加密后台直接公开。

```bash
sudo journalctl -u outreach-worker -n 100 --no-pager
sudo -u outreach env OUTREACH_DATA_DIR=/var/lib/book-reader-outreach \
  /opt/book-reader-outreach/.venv/bin/python -m outreach.cli status
sudo -u outreach env OUTREACH_DATA_DIR=/var/lib/book-reader-outreach \
  /opt/book-reader-outreach/.venv/bin/python -m outreach.cli pause
```

备份使用CLI `backup --output`，选择只有服务用户可写的私有位置，不能放到Web静态目录。schema、回退和恢复边界参见 [当前升级指南](UPGRADE_ROLLBACK_1.3.md)，将其中Compose停启步骤换成相应systemctl操作，不直接使用旧版本升级脚本。保留源码、虚拟环境、数据及密钥，更新后核查并恢复已获授权的开关。

默认自动化关闭；配置流程、联系资格和邮箱保护与Compose相同。此页是原生操作示例，不表示本轮已在原生systemd上真实部署验收。

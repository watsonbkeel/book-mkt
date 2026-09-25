# 原生 Debian + systemd（Compose之外的备选）

要求Python 3.11+、venv、系统CA证书与网络出站。自动测试实际在Python3.13.5运行；Debian原生解释器仍需执行同样测试。以下命令会创建独立用户、目录和两个服务；由服务器管理员核对后执行，不覆盖现有业务。

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip ca-certificates unzip
sudo useradd --system --home /var/lib/book-reader-outreach --shell /usr/sbin/nologin outreach
sudo mkdir -p /opt/book-reader-outreach
# 把解压出来的整个包内容复制到 /opt/book-reader-outreach 后继续
cd /opt/book-reader-outreach
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo install -d -m 700 -o outreach -g outreach /var/lib/book-reader-outreach
sudo -u outreach env OUTREACH_DATA_DIR=/var/lib/book-reader-outreach \
  /opt/book-reader-outreach/.venv/bin/python -m outreach.cli init --seed-history
# 保存上一步随机密码
sudo cp deploy/outreach-web.service deploy/outreach-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now outreach-web outreach-worker
sudo systemctl status outreach-web outreach-worker
```

默认仅监听127.0.0.1:8096，使用README里的SSH隧道访问。启用公网HTTPS后，在outreach-web.service中把OUTREACH_SECURE_COOKIE改为true，daemon-reload并重启web。不要在公网使用未加密HTTP登录。

```bash
sudo journalctl -u outreach-worker -n 100 --no-pager
sudo -u outreach env OUTREACH_DATA_DIR=/var/lib/book-reader-outreach \
  /opt/book-reader-outreach/.venv/bin/python -m outreach.cli pause
```

备份：选择只有outreach用户能写的私有目录，例如 `/var/lib/book-reader-backups`；使用 `python -m outreach.cli backup --output ...`。不要把含主密钥的备份放入Nginx静态目录。

系统日期、DNS与证书必须正确；SMTP/IMAP使用应用密码而不是在支持OAuth但禁密码的账号上硬试。服务器出站防火墙要允许对应邮件端口与HTTPS443。

现有部署切换代码前必须备份并按`升级与回退_v1.2.md`执行。旧时区不随版本默认值改变，设置页确认应用美东预设后再启用。

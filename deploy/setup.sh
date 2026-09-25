#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
command -v docker >/dev/null || { echo 'Docker尚未安装；请由服务器管理员按官方Debian说明安装，脚本不会擅自安装系统组件。' >&2; exit 1; }
docker compose version >/dev/null || { echo '需要Docker Compose插件。' >&2; exit 1; }
[[ -f .env ]] || cp .env.example .env
chmod 600 .env
docker compose config -q
docker compose build
echo '接下来初始化管理员；新密码只在本终端显示一次，请保存。'
docker compose run --rm --no-deps web python -m outreach.cli init
docker compose up -d
sleep 3
docker compose ps
printf '\n站点只绑定服务器127.0.0.1:8096（自定义端口以.env为准）。\n先用SSH隧道访问；默认全部自动化暂停，不会发信。\n'

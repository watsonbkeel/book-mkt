#!/usr/bin/env bash
# Upgrade only the default Compose deployment; never reset data or credentials.
set -euo pipefail
new="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
if [[ $# -ne 2 || "$2" != '--confirm-pause' ]]; then
  echo '用法：bash deploy/upgrade.sh /旧版源码的绝对目录 --confirm-pause' >&2
  echo '会先停旧Worker和网页、备份数据库与密钥、升级同一数据卷；升级后自动化保持暂停。' >&2
  exit 2
fi
old="$(cd "$1" && pwd -P)"
[[ "$new" != "$old" ]] || { echo '新旧目录必须不同，不能覆盖原代码。' >&2; exit 2; }
for dir in "$old" "$new"; do
  [[ -f "$dir/compose.yaml" && -f "$dir/VERSION" ]] || { echo "不是有效项目目录：$dir" >&2; exit 2; }
  grep -Eq '^name: book-reader-outreach$' "$dir/compose.yaml" || { echo '此脚本只支持默认Compose项目名，自定义卷/覆盖文件请按升级文档人工处理。' >&2; exit 2; }
  for override in compose.override.yaml compose.override.yml docker-compose.override.yml docker-compose.override.yaml; do
    [[ ! -f "$dir/$override" ]] || { echo '存在Compose覆盖配置，请按升级文档人工处理。' >&2; exit 2; }
  done
done
[[ -f "$old/.env" ]] || { echo '旧目录缺少.env，停止；不要用默认配置猜数据卷。' >&2; exit 2; }
old_version="$(tr -d '\r\n' < "$old/VERSION")"
[[ "$old_version" == '1.0.0' || "$old_version" == '1.1.0' || "$old_version" == '1.2.0' ]] || { echo '仅支持1.0.0/1.1.0/1.2.0→1.3.0；其他情况按文档处理。' >&2; exit 2; }
[[ "$(tr -d '\r\n' < "$new/VERSION")" == '1.3.0' ]] || { echo '新目录必须为1.3.0。' >&2; exit 2; }
if [[ -f "$new/.env" ]]; then
  cmp -s "$old/.env" "$new/.env" || { echo '新旧.env不同，先核对；不自动覆盖。' >&2; exit 2; }
else cp "$old/.env" "$new/.env"; fi
chmod 600 "$new/.env"
# Fail closed for externally overridden project/file settings.
[[ -z "${COMPOSE_PROJECT_NAME:-}" && -z "${COMPOSE_FILE:-}" ]] || { echo '检测到Compose环境覆盖，先按升级文档核对卷。' >&2; exit 2; }
if grep -Eq '^(COMPOSE_PROJECT_NAME|COMPOSE_FILE)=' "$old/.env"; then echo '检测到.env项目覆盖，请人工核对数据卷。' >&2; exit 2; fi
command -v docker >/dev/null
docker compose version >/dev/null
newc() { (cd "$new" && docker compose -f compose.yaml "$@"); }
oldc() { (cd "$old" && docker compose -f compose.yaml "$@"); }
newc config -q;oldc config -q
# Build before downtime. Different image tag prevents replacing old rollback image.
newc build
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="$new/backups";mkdir -p "$backup_dir";chmod 700 "$backup_dir"
name="pre-v1.3-${stamp}.zip";container="reader-upgrade-${stamp}"
oldc stop worker web
# One-off old-code container performs SQLite online backup; no daemon starts.
oldc run --name "$container" --no-deps -T web python -m outreach.cli backup --output "/tmp/$name"
docker cp "$container:/tmp/$name" "$backup_dir/$name"
chmod 600 "$backup_dir/$name"
[[ -s "$backup_dir/$name" ]] || { echo '备份文件为空，停止升级；旧服务保持停止。' >&2; exit 1; }
python3 - "$backup_dir/$name" <<'VERIFY'
import hashlib,json,sys,zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
    if set(z.namelist()) != {'outreach.sqlite3','master.key','backup.json'} or len(z.namelist()) != 3 or z.testzip():
        raise SystemExit('Invalid backup entries/checksum; migration stopped')
    if any(i.file_size > 500_000_000 for i in z.infolist()):raise SystemExit('Backup too large')
    meta=json.loads(z.read('backup.json'))
    if meta.get('format') != 1 or hashlib.sha256(z.read('outreach.sqlite3')).hexdigest() != meta.get('database_sha256') or len(z.read('master.key').strip()) != 44:
        raise SystemExit('Backup database/key verification failed; migration stopped')
VERIFY
docker rm "$container" >/dev/null
printf '私有升级前备份：%s\n' "$backup_dir/$name"
# Migration preserves the named volume and master.key, and disables automation.
newc run --rm --no-deps -T web python -m outreach.cli init
newc run --rm --no-deps -T web python -m outreach.cli pause
newc up -d
newc ps
printf '\n升级步骤完成；必须核查/health、收信小时周期、旧记录和待审草稿，再手动启用。\n'
printf '不要用旧版代码打开已迁移的数据库；回退需恢复上面的备份到新空卷。\n'

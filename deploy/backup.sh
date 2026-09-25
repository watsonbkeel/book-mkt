#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "${BASH_SOURCE[0]}")/.."
mkdir -p backups; chmod 700 backups
stamp="$(date -u +%Y%m%dT%H%M%SZ)"; file="outreach-${stamp}.zip"
docker compose exec -T web python -m outreach.cli backup --output "/tmp/$file"
docker compose exec -T web python -c 'import sys, pathlib; sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())' "/tmp/$file" > "backups/$file"
chmod 600 "backups/$file"
unzip -tq "backups/$file" >/dev/null
remote_hash="$(docker compose exec -T web sha256sum "/tmp/$file" | cut -d' ' -f1)"
local_hash="$(sha256sum "backups/$file" | cut -d' ' -f1)"
[[ "$remote_hash" == "$local_hash" ]] || { echo '备份复制校验失败，容器内原件未删除。' >&2; exit 1; }
docker compose exec -T web python -c 'import sys, pathlib; pathlib.Path(sys.argv[1]).unlink()' "/tmp/$file"
printf '已创建私有备份：backups/%s\n此ZIP含邮箱/API密钥解密材料，严禁公开。\n' "$file"

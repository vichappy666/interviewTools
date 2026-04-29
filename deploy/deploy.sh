#!/usr/bin/env bash
# 简单部署脚本：git pull + 后端重启 + 前端 rebuild。
# 运行环境：interview 用户在 /srv/interview/repo 下。
set -euo pipefail

REPO=/srv/interview/repo
WEB_USER_DIST=/var/www/web-user/dist
WEB_ADMIN_DIST=/var/www/web-admin/dist

echo "==> git pull"
cd "$REPO"
git pull --ff-only

echo "==> backend deps"
cd "$REPO/backend"
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -e ".[dev]" --quiet

echo "==> alembic migrate"
alembic upgrade head

echo "==> rebuild & deploy web-user"
cd "$REPO/web-user"
npm ci --silent
npm run build
sudo rsync -a --delete dist/ "$WEB_USER_DIST/"

echo "==> rebuild & deploy web-admin"
cd "$REPO/web-admin"
npm ci --silent
npm run build
sudo rsync -a --delete dist/ "$WEB_ADMIN_DIST/"

echo "==> restart backend"
sudo systemctl restart interview-backend

echo "==> reload caddy"
sudo systemctl reload caddy

echo "==> done"
sudo systemctl status interview-backend --no-pager | head -10

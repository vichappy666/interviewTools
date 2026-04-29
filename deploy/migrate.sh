#!/usr/bin/env bash
# 单独跑 alembic upgrade（不动代码）。常用于先迁移再发布场景。
set -euo pipefail

cd /srv/interview/repo/backend
# shellcheck disable=SC1091
source .venv/bin/activate
alembic upgrade head

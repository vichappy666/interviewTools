# 部署产物

完整部署文档请见 [`docs/deployment-vps.md`](../docs/deployment-vps.md)。

本目录包含：

- `interview-backend.service`：systemd unit 模板
- `Caddyfile.example`：Caddyfile 模板（占位 `app.example.com` / `admin.example.com`）
- `.env.prod.example`：生产 `.env` 模板
- `deploy.sh`：拉代码 + 重启 + 前端重建
- `migrate.sh`：单独跑 alembic upgrade

部署到 VPS 时复制这些文件到对应位置（systemd unit 到 `/etc/systemd/system/`，
Caddyfile 到 `/etc/caddy/Caddyfile`，脚本可放 `/srv/interview/scripts/` 或保留在仓库下直接执行）。

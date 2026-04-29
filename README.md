# 面试助手 SaaS

> 实时语音转写 + 多模型 AI 助答的云端面试辅助工具。
> v1.0.0 起为云端 SaaS（FastAPI + Vue 3）；旧版本 PySide6 桌面端归档于 [`legacy/`](legacy/)。

---

## 架构概览

```
[ Browser: web-user ]  ─┐
                        │              ┌──> Volcengine ASR (WebSocket)
                        ├── HTTPS ──>  │
[ Browser: web-admin ]  │  REST + WS   │──> DeepSeek / OpenAI / Claude / Gemini
                        ├──────────>  [ FastAPI backend ] ──> [ MySQL ]
                                       │
                                       └──> TronGrid（USDT-TRC20 充值核销）
```

| 模块 | 技术栈 | 职责 |
|------|-------|------|
| `backend/` | FastAPI 0.110 · SQLAlchemy 2.0 · Alembic · bcrypt · PyJWT · httpx | 账号 / 余额 / 面试 WebSocket / ASR / LLM / TRC20 充值 |
| `web-user/` | Vue 3 · Vite · TypeScript · Pinia | 用户端（注册 / 面试 / 充值 / 历史回看） |
| `web-admin/` | Vue 3 · Element Plus · Pinia | 管理后台（用户 / 充值订单 / 系统配置） |
| `legacy/` | PySide6 · Qt | v0.3.0 之前的本地桌面端，已归档 |

---

## 功能

- 注册 / 登录 / 改密码（bcrypt + JWT，登录限流）
- 余额账本（balance_ledger）+ admin 加减时间
- 多设备并发面试（弹"加入 / 新开 / 取消"）
- 实时 ASR（火山引擎流式，自动问题检测）
- LLM 三段并行流（要点 / 话术 / 完整答案）
- 按 wall-clock 秒扣费（结束面试时一笔 ledger）
- USDT-TRC20 充值（D 方案：from-address 绑定 + 7 项链上校验，含 Shasta 测试网）
- 历史面试详情回看（含 LLM 三段）
- admin 后台：用户 / 充值订单（强制成功 / 失败 / 重置）/ 系统配置

---

## 快速开始（本机 dev，约 30 分钟）

### 前置环境

- Python 3.11+
- Node 20+
- MySQL 8（或 5.7+）
- macOS / Linux（Windows 用 WSL2）

### 1. 准备数据库

```bash
mysql -u root -p
mysql> CREATE DATABASE interview_assistant CHARACTER SET utf8mb4;
mysql> exit
```

### 2. 启动后端

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env       # 编辑 DATABASE_URL / JWT_SECRET / CORS_ORIGINS
alembic upgrade head        # 建表 + seed 默认 admin（admin / admin）
uvicorn app.main:app --reload --port 8000
```

### 3. 启动两个前端

```bash
# 终端 A
cd web-user && npm install && npm run dev    # http://localhost:5173

# 终端 B
cd web-admin && npm install && npm run dev   # http://localhost:5174
```

### 4. 登录 admin 后台

打开 http://localhost:5174 ，默认账号 `admin / admin`（**上线前必须改**）。

### 5. 配置 ASR / LLM 凭证（必做）

进 admin → "系统配置"，按需填写：

```jsonc
// asr.volcengine
{
  "app_key": "你的 volcengine app key",
  "access_key": "你的 volcengine access key",
  "resource_id": "volc.bigasr.sauc.duration"
}

// llm.providers（数组，每个模型一项）
[
  {"name": "deepseek", "api_key": "sk-xxx", "model": "deepseek-chat"}
]

// llm.default
"deepseek"
```

可选（启用 USDT-TRC20 充值）：

| key | 默认值 / 示例 | 说明 |
|-----|--------------|------|
| `recharge.network` | `shasta` 或 `mainnet` | 测试网 / 主网 |
| `recharge.to_address` | `Txxxxxxxx...`（34 字符）| 平台 USDT-TRC20 收款地址 |
| `recharge.tron_api_key` | 可选 | TronGrid API key（生产强烈推荐） |
| `recharge.rate_per_usdt` | `60` | 每 1 USDT 兑换多少秒面试时间 |
| `recharge.min_amount_usdt` | `1` | 单笔最低充值金额 |

### 6. 跑通流程

1. http://localhost:5173 注册一个用户账号
2. admin 后台 → 用户管理 → 找到该账号 → "加时间" 加 60 分钟
3. 用户端首页 → "🎤 开始面试" → 浏览器允许麦克风
4. 说话 → 看到实时转写 + LLM 三段答案
5. 结束面试 → 首页"最近面试"点进去看历史 QA

---

## 配置参考

### `backend/.env.example`

```env
# 数据库（生产请用强密码或专用账号）
DATABASE_URL=mysql+pymysql://root:password@localhost:3306/interview_assistant

# JWT（生产必改：openssl rand -hex 32）
JWT_SECRET=please-run-openssl-rand-hex-32-and-paste-here
JWT_EXPIRE_DAYS=7

# 跨域（CSV，dev 端口 5173/5174）
CORS_ORIGINS=http://localhost:5173,http://localhost:5174

# 部署环境标记（dev / prod）
ENV=local

# TronGrid（可选；不配也能用，仅速率受限）
TRONGRID_API_KEY=
```

### 前端 vite env

默认通过 vite proxy 走同源。需要指定后端 URL 时：

```env
# web-user/.env.local 或 web-admin/.env.local
VITE_API_BASE_URL=http://localhost:8000
```

---

## 测试

```bash
# 后端单测（in-memory SQLite，无外网依赖）
cd backend && source .venv/bin/activate
pytest -q                                # 全量（应 250+ passed）
pytest tests/test_recharge_submit.py -v  # 充值核销单文件

# 前端构建检查
cd web-user && npm run build
cd web-admin && npm run build
```

---

## 部署到 VPS

完整生产部署指南（Ubuntu 22.04 + Caddy 自动 HTTPS + systemd + MySQL）见
[`docs/deployment-vps.md`](docs/deployment-vps.md)。配套部署产物在 [`deploy/`](deploy/)：
systemd unit、Caddyfile 模板、`deploy.sh` 升级脚本、`.env.prod.example`。

跟着文档跑大约 1 小时即可上线含 HTTPS 的服务（v1.1.0 起）。

---

## 旧版本（v0.3.0 桌面端）

`legacy/` 是 PySide6 桌面端代码，已归档不再维护。

回滚到桌面版：
```bash
git checkout v0.3.0-web-layout
```

---

## 里程碑

| Tag | 状态 | 内容 |
|-----|------|------|
| `v0.3.0-web-layout` | ✅ | 桌面端最后一版（参考） |
| `v0.4.0-m0` | ✅ | 工程脚手架（FastAPI + Vue + Alembic + 测试基建） |
| `v0.4.0-m1` | ✅ | 账号 + 余额 + admin 后台 |
| `v0.4.0-m2` | ✅ | 面试核心：ASR async + LLM 三段并行流 + WebSocket + 扣费 meter |
| `v0.4.0-m3` | ✅ | TRC20 充值（D 方案，含 base58check 手写 + 7 项链上校验） |
| `v1.0.0` | ✅ | 历史回看 + 体验打磨 + README（**第一版正式 release**） |
| `v1.1.0` | 🚧 | 首次可上线版（VPS 部署文档 + systemd + Caddy 产物） |

---

## License

私有项目；具体许可条款见 `LICENSE`（如有）。

---

## 文档

- 总设计：[`docs/superpowers/specs/2026-04-29-account-and-frontend-design.md`](docs/superpowers/specs/2026-04-29-account-and-frontend-design.md)
- 各阶段实施计划：`docs/superpowers/plans/`

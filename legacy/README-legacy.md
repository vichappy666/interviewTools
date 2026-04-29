# legacy/ — 重构前的桌面端代码

本目录是 v0.3.0 及之前的实现：基于 PySide6 桌面 Qt UI + 本机内嵌 aiohttp Web 镜像的本地工具。

**已不再维护。** 仅保留：
- 作为云端 SaaS 重构的参照
- 万一新方案翻车的回滚备份

要回滚到这个版本，使用：
```
git checkout v0.3.0-web-layout
```

新版云端 SaaS 见根目录 `backend/` `web-user/` `web-admin/`。

文件清单：
- `ui.py` — Qt 主窗口（TranscriptView/AnswerView/...）
- `main.py` — Qt 应用入口 + Worker 编排
- `audio_capture.py` — PyAudio 本地麦采集
- `web_server.py` — 本机 aiohttp + Qt 桥
- `web/index.html` — 浏览器镜像 UI
- `asr.py` `llm.py` `question_detector.py` `stream_parser.py` — 业务模块（已搬迁副本到 backend/app/）
- `config.py` — MySQL config 读取（M1 时会被 backend/app/config.py 取代）
- `requirements.txt` — 旧依赖

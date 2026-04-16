# 面试助手 (Interview Assistant)

Mac 平台的实时面试辅助工具：通过麦克风采集语音 → 火山引擎流式 ASR 实时转写（边说边出字）→ 识别问题 → 调用云端 LLM 生成答案 → 悬浮窗显示。

## 功能

- **流式语音识别**：火山引擎大模型 ASR（Seed-ASR），持久 WebSocket 连接，延迟 < 500ms，边说边出字
- **LLM 四选一**：Claude / OpenAI / Grok / Gemini，设置面板填 API key
- **问题检测**：从转写流里自动识别问题并触发 LLM
- **悬浮窗**：永远置顶、半透明、可拖动，深色主题
- **配置管理**：API key 从 MySQL 读取，敏感信息不落配置文件

## 准备工作

### 1. Python 环境

需要 Python 3.10+。

```bash
cd interviewTools
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. MySQL 配置

API key 统一存储在本地 MySQL 的 `interview_assistant` 数据库 `config` 表中：

```sql
CREATE DATABASE IF NOT EXISTS interview_assistant;
USE interview_assistant;

CREATE TABLE IF NOT EXISTS config (
  `key` VARCHAR(64) PRIMARY KEY,
  `value` TEXT,
  `description` VARCHAR(255) DEFAULT ''
);

-- 按需插入你的 key
INSERT INTO config (`key`, `value`) VALUES
  ('volcengine_app_key', 'your-volcengine-app-key'),
  ('volcengine_access_key', 'your-volcengine-access-key'),
  ('grok_api_key', 'your-grok-key'),
  ('claude_api_key', 'your-claude-key'),
  ('openai_api_key', 'your-openai-key'),
  ('gemini_api_key', 'your-gemini-key');
```

程序启动时自动从 MySQL 读取，覆盖本地配置文件中的空值。

### 3. 火山引擎 ASR 申请

在火山引擎控制台开通豆包语音服务，获取 App Key 和 Access Key。  
文档：https://www.volcengine.com/docs/6561/1354869

## 运行

```bash
source .venv/bin/activate
python main.py
```

### 启动流程

1. **加载配置**：读取 `~/.interview_assistant/config.json`，若不存在则用默认配置创建
2. **读取 MySQL key**：连接本地 MySQL `interview_assistant.config` 表，读取所有 API key；连不上则跳过
3. **创建悬浮窗**：显示 PySide6 悬浮窗 UI
4. **初始化 Worker**：
   - 创建 `StreamingASR`：建立持久 WebSocket 连接到火山引擎
   - 创建 `AudioCapture`：打开 MacBook 麦克风，每 100ms 回调一帧音频直接发给 ASR
   - 创建 LLM 客户端和问题检测器
5. **实时转写**：麦克风采集音频 → 100ms 一帧发送到火山引擎 → 服务端实时返回 partial/final result → UI 实时刷新

### 使用方法

启动后：

1. 悬浮窗右上角点 **⚙** 打开设置
2. **语音识别标签页**：填写火山引擎 App Key 和 Access Key
3. **LLM 标签页**：选一个 provider，填对应 API key
4. **音频标签页**：默认使用 MacBook 麦克风，可改为其他输入设备
5. 确认后程序自动重启音频 pipeline

转写区会实时显示识别结果（单行刷新，说完一句后换行固定），检测到问题后自动调用 LLM 生成回答。

## 架构

```
麦克风 (100ms/帧)
    ↓ callback
AudioCapture
    ↓ feed(pcm)
StreamingASR (持久 WebSocket → wss://openspeech.bytedance.com)
    ↓ on_partial(text) / on_final(text)
Worker (Qt Signals)
    ↓                    ↓
UI 转写区              QuestionDetector
(单行实时刷新)              ↓
                        LLM → UI 回答区
```

## 项目结构

```
interviewTools/
├── main.py              # 入口，Worker 串联所有模块（回调驱动）
├── config.py            # 配置加载/保存，MySQL key 读取
├── audio_capture.py     # 麦克风音频采集（100ms 帧回调）
├── asr.py               # 火山引擎流式 ASR（持久 WebSocket + 自动重连）
├── question_detector.py # 规则版问题检测
├── llm.py               # 四家云端 LLM 封装
├── ui.py                # PySide6 悬浮窗 + 设置面板（深色主题）
└── requirements.txt
```

## 配置文件

本地配置存放在 `~/.interview_assistant/config.json`，用于保存非敏感设置（模型名称、音频设备等）。API key 优先从 MySQL 读取，本地配置作为兜底。

## 常见问题

**Q: 启动报 "找不到输入设备"?**  
A: 默认使用 `MacBook Pro麦克风`。如果设备名不同，在设置 → 音频标签页修改，或直接改 `config.json` 里的 `input_device_name`。控制台会列出当前可用的输入设备。

**Q: 连接报 503 / 代理错误?**  
A: 火山引擎是国内服务，程序已自动绕过代理直连。如果仍有问题，检查你的科学上网工具是否拦截了 `openspeech.bytedance.com`，将其加入直连规则。

**Q: 转写延迟多少?**  
A: 流式 ASR 延迟约 200-500ms（边说边出字）。LLM 回答延迟额外 2-3 秒。

**Q: 问题检测不准?**  
A: 当前是规则版（问号 + 疑问词 + 静音超时）。可以调 `config.json` 里的 `silence_seconds` 和 `min_chars`。

**Q: MySQL 连不上怎么办?**  
A: 程序会自动降级到本地 `config.json` 中的配置。如果本地配置里也没有 key，需要在设置面板手动填入。

**Q: ASR 断线了怎么办?**  
A: 程序会自动重连（最多 3 次，指数退避）。重连期间音频帧会丢弃，重连成功后恢复正常。

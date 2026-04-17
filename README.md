# 面试助手 (Interview Assistant)

Mac 平台的实时面试辅助工具：麦克风采集语音 → 火山引擎流式 ASR 实时转写 → 识别问题进入队列 → 手动挑题发给 LLM → 三段结构化答案并行流式显示。

## 功能

- **流式语音识别**：火山引擎大模型 ASR（Seed-ASR），持久 WebSocket，延迟 < 500ms，边说边出字
- **五个 LLM 可选**：DeepSeek（默认，真流式） / Claude / OpenAI / Grok / Gemini
- **手动挑题**：识别到的问题进右侧队列，点哪条才发哪条，不浪费 token
- **三段并行回答**：要点（bullet 速览）/ 话术（口语可直接说）/ 完整答案（详细）三段**同时生成**，每段独立流式显示
- **转写区选中发问**：在实时转写里划选任意文本，弹气泡 → 问 AI
- **问题列表选中发问**：右侧队列也支持跨条划选 → 问 AI
- **真取消**：切题立即关闭 HTTP 流，旧题不再浪费 token
- **悬浮窗**：半透明、可拖动、深色主题（920×1040）
- **🌐 Web 镜像 UI**：一键在浏览器打开同构页面，跟 Qt 窗口双向同步；浏览器里可点击问题、划选发问、手动输入，多端可同时连（办公桌 + iPad）
- **📌 跨 App 置顶（macOS）**：PyObjC 直接把 NSWindow level 抬到 `NSStatusWindowLevel`，并设置 `CanJoinAllSpaces + FullScreenAuxiliary`，切到别的 App / Space / 全屏应用都浮在最上层（类似微信视频小窗）

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

API key 统一存在本地 MySQL 的 `interview_assistant.config` 表：

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
  ('volcengine_app_key',    'your-volcengine-app-key'),
  ('volcengine_access_key', 'your-volcengine-access-key'),
  ('deepseek_api_key',      'your-deepseek-key'),
  ('grok_api_key',          'your-grok-key'),
  ('claude_api_key',        'your-claude-key'),
  ('openai_api_key',        'your-openai-key'),
  ('gemini_api_key',        'your-gemini-key');
```

程序启动时自动读取，覆盖本地配置文件中的空值。

### 3. 火山引擎 ASR 申请

在火山引擎控制台开通豆包语音服务，获取 App Key / Access Key。文档：https://www.volcengine.com/docs/6561/1354869

### 4. DeepSeek API Key（默认 LLM）

去 [DeepSeek 开放平台](https://platform.deepseek.com/) 申请 API key，写入 MySQL 的 `deepseek_api_key`。

## 运行

```bash
source .venv/bin/activate
python main.py
```

## 界面

```
┌─────────────────────────────────────────────────────────────┐
│ ● 面试助手 · 监听中                        📌 🌐 ⚙  ✕       │
├──────────────────────────────┬──────────────────────────────┤
│ 实时转写                      │ 识别的问题  (点击发问)        │
│ ┌──────────────────────────┐ │ ┌──────────────────────────┐ │
│ │ ... 转写文本（可划选）...   │ │ │ 问题 1                    │ │
│ │ 划选 → [🤖 问 AI] 气泡    │ │ │ 问题 2 (已问·灰色)         │ │
│ └──────────────────────────┘ │ │ 问题 3 (可跨条划选)        │ │
│                              │ └──────────────────────────┘ │
├──────────────────────────────┴──────────────────────────────┤
│ AI 回答                                                      │
│                                                             │
│ Q: xxx                                                       │
│                                                             │
│ 要点                      [📋 复制]  ⏳ 生成中               │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ • point 1                                               │ │
│ │ • point 2                                               │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ 话术                      [📋 复制]  ⏳ 生成中               │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 自然口语化回答...                                         │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ 完整答案                  [📋 复制]  ⏳ 生成中               │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 详细解释，支持 **加粗**、bullet、多段落                    │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## 使用流程

1. 启动 app，右上角 **⚙** 打开设置，确认 ASR + LLM provider 配置
2. 开始说话，左侧转写区边说边出字
3. 说完一句问题（含 ?/？ 或 "什么 / 怎么 / 原理" 等词）→ 右侧队列自动加一条
4. **想问 AI 时**：
   - 点右侧队列的某条 → 整句发给 AI
   - 或在转写区 / 队列里划选任意文字 → 弹出 **[🤖 问 AI]** 气泡 → 点击发送
5. AI 回答区三段（要点 / 话术 / 完整答案）**同时开始生成**，每段状态：等待中 → ⏳ 生成中 → ✓ 已完成
6. 点每段右上角 **[📋 复制]** 把该段文字拷到剪贴板（自动去 Markdown 符号）
7. 切到下一题时：旧题的三段流立即中止（关 HTTP 连接，不再计 token），UI 清空重开
8. 想在浏览器里用时，点 **🌐** 打开 `http://127.0.0.1:8765`，Qt 窗口和网页实时双向同步
9. 想在切别的 App 时仍保持窗口可见，保留 **📌** 按下（默认已按下）；点一下可取消置顶

## 架构

```
麦克风 (100ms/帧)
    ↓
AudioCapture
    ↓ feed(pcm)
StreamingASR (持久 WebSocket, 句级去重)
    ↓ on_partial / on_final
Worker (Qt Signals)                       识别的问题
    ↓ partial_text / final_text           ← (点击) / (划选 + 气泡) / 浏览器
 TranscriptView  +  QuestionDetector      ↓
 (Qt)          ↓ 每句独立判断           Worker.ask(text)
                    问题                      ↓
                    ↓                    _dispatch_parallel_stream
              QuestionListView         ───┬──┬──┐
              (可跨条划选)              key  script full
                    │                   ↓    ↓    ↓
                    │             3 个并行线程（各自 ask_stream）
                    │                   ↓    ↓    ↓
                    │              AnswerView 三段面板（流式 append）
                    │                        │
                    └────── 同一批 Signal ────┤
                                             ▼
                              WebBridge (asyncio 线程)
                              ├─ 状态快照 (供新连接补齐)
                              ├─ aiohttp HTTP/WS @ 127.0.0.1:8765
                              └─ 广播给所有浏览器 + 接受入站命令
                                             ▼
                                      浏览器镜像 UI
                              (HTML + vanilla JS，无构建)
```

## 项目结构

```
interviewTools/
├── main.py              # 入口 + Worker（信号中枢 + 并行流式调度 + token 取消）+ WebBridge 挂载
├── config.py            # 配置加载/保存 + MySQL key 读取
├── audio_capture.py     # 麦克风音频采集（100ms 帧回调）
├── asr.py               # 火山引擎流式 ASR（持久 WebSocket + 重连 + 句级去重）
├── question_detector.py # 每句独立判断（末尾 ?/？ 直判 + 关键词）
├── llm.py               # 5 家 LLM 封装 + SYSTEM_PROMPT_V2 + SECTION_PROMPTS
├── stream_parser.py     # 单请求三段切分器（当前未使用，v2 已改并行）
├── ui.py                # PySide6 UI 组件
│   ├── TranscriptView     转写区，选区保护 + 浮动气泡
│   ├── QuestionListView   问题队列（QTextBrowser，支持跨条划选）
│   ├── AnswerView         三段面板（要点 / 话术 / 完整答案）
│   ├── SelectionPopup     [🤖 问 AI] 浮动气泡
│   └── FloatingWindow     悬浮窗主体（含 📌 置顶 / 🌐 Web / ⚙ 设置 按钮 + macOS NSWindow level）
├── web_server.py        # WebBridge：asyncio+aiohttp 后台线程，Qt 信号 ↔ 浏览器 双向桥接
├── web/
│   └── index.html       # 浏览器端镜像 UI（vanilla JS，无构建；DOM 稳定结构防选区丢失）
└── requirements.txt
```

## 关键设计点

- **三段并行**：对同一问题并行发起 3 个 LLM 请求（3 个 prompt 分别聚焦要点 / 话术 / 完整），延迟 = max(三段) 而非 sum
- **真取消**：`ask_stream` 用 `try/finally` + `stream.close()`；切题时 `generator.close()` → 底层 HTTP 立即断，不再计 token
- **选区保护（Qt）**：TranscriptView 用独立 `QTextCursor(doc)` 改文本，**永不调 `setTextCursor`**，用户选区不被 partial 刷新打断
- **选区保护（Web）**：`#transcript` 里塞两个常驻 Text 节点，finals 只 `appendData`（偏移量只扩展），partial 只改自己；问题列表用增量 DOM（append / classList.toggle）不重建，跨条划选不被新数据挤掉
- **ASR 去重**：火山引擎有时会改写历史文本（如 "你好。" → "你好，"）并重发整段，asr.py 按句归一化（去标点/空白）比对最近 30 句，防重复 commit
- **问题列表**：单个 `QTextBrowser`（而非多个独立 widget），每问题一 block，支持跨条划选；`selectionChanged` 自动关气泡
- **跨 App 置顶**：macOS 下 `Qt.Tool` 对应 NSPanel，默认 App 失焦会 `orderOut:`；通过 PyObjC 对 NSWindow 调 `setLevel_(NSStatusWindowLevel)` + `setHidesOnDeactivate_(False)` + `setCanHide_(False)` 强制浮在所有 App 之上
- **Web 双向同步**：Worker 的所有信号 fan-out 到 `FloatingWindow` + `WebBridge`；浏览器命令经 `Qt.QueuedConnection` 跨线程回送 `worker.ask`；新连接自动收到完整 snapshot（转写 / 问题 / 当前回答）

## 配置文件

本地配置在 `~/.interview_assistant/config.json`，保存非敏感设置（模型名、音频设备等）。API key 优先从 MySQL 读，本地作兜底。

Web 镜像 UI 相关字段：

```json
"web": {
  "enabled": true,
  "host": "127.0.0.1",
  "port": 8765
}
```

> `enabled: false` 可彻底关闭内置 Web 服务；`host` 保持 `127.0.0.1` 限制本机访问（避免 API key 泄漏），不建议改。

## 常见问题

**Q: 启动报 "找不到输入设备"?**  
A: 默认用 `MacBook Pro麦克风`。设备名不同就在设置 → 音频标签页改，或直接改 `config.json` 里的 `input_device_name`。控制台会列出当前可用的输入设备。

**Q: 连接报 503 / 代理错误?**  
A: 火山引擎和 DeepSeek 都是国内服务，程序已自动把 `openspeech.bytedance.com` 和 `api.deepseek.com` 加入 NO_PROXY。仍有问题就检查科学上网工具是否拦截了这两个域名，加入直连。

**Q: 转写延迟多少?**  
A: 流式 ASR 延迟约 200-500ms。LLM 回答首 token 约 1s（DeepSeek），三段并行总耗时约等于最慢那段（6-10s 内）。

**Q: 问题检测不准?**  
A: 每句独立判断。末尾 `?/？` 直接判定；否则看是否含 "什么 / 怎么 / 原理" 等关键词。漏了就在转写区划选 → 气泡发问。

**Q: 问了半天 AI 还没答，想切另一题怎么办?**  
A: 直接点新题。旧题的 3 个流会立即关断（HTTP 连接关闭），新题马上开始。不浪费 token。

**Q: MySQL 连不上怎么办?**  
A: 程序自动降级到本地 `config.json`。本地也没 key 就在设置面板手动填。

**Q: ASR 断线了怎么办?**  
A: 自动重连（最多 3 次，指数退避）。重连期间音频帧丢弃，重连成功后恢复正常。

**Q: 切到别的 App 后 Qt 窗口被盖住?**  
A: 点顶栏 **📌** 按钮保持按下（默认是按下的）。实现是 PyObjC 改 NSWindow level 到 `NSStatusWindowLevel`，同时 `setHidesOnDeactivate_(False)`，这样在 App 失焦、全屏应用、Space 切换下都能浮在最上层。仍有问题通常是 PyObjC 没装好，检查 `pip install pyobjc-framework-Cocoa` 是否成功。

**Q: 浏览器里的 🌐 Web UI 和 Qt 窗口能同时用吗?**  
A: 能。多端（Qt + 多个浏览器）看到完全一致的状态，任意端的操作（点击发问、划选发问、手动输入）都会广播给其他端。适合 Mac 开会、iPad 看答案的场景。音频采集和 LLM 调用只在 Qt 进程里做一次。

**Q: Web UI 端口被占了?**  
A: 改 `~/.interview_assistant/config.json` 里的 `web.port` 字段，重启即可。

**Q: Web UI 划选历史文字，新识别的字一进来就把选区挤掉了?**  
A: 已修。转写区用两个常驻 Text 节点（finals 只 `appendData`，partial 只改自己），问题列表用增量 DOM，新数据进来不会销毁老 DOM，选区不丢。

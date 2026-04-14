# 面试助手 (Interview Assistant)

Mac 平台的实时面试辅助工具:捕获面试软件的系统音频 → 实时转写成文字 → 识别问题 → 调用云端 LLM 生成答案 → 悬浮窗显示。

## 功能

- **ASR 双引擎**:faster-whisper 本地 / 阿里云流式,UI 上一键切换
- **LLM 四选一**:Claude / OpenAI / Grok / Gemini,设置面板填 API key
- **问题检测**:从转写流里自动识别问题并触发 LLM
- **悬浮窗**:永远置顶、半透明、可拖动

## 准备工作

### 1. 安装 BlackHole(虚拟声卡)

```bash
brew install blackhole-2ch
```

### 2. 配置音频路由

打开 macOS 的 **音频 MIDI 设置**(Audio MIDI Setup):

1. 左下角 `+` → 创建 **多输出设备**
2. 勾选你的耳机(或扬声器)+ BlackHole 2ch
3. 在面试软件(Zoom / Meet / 腾讯会议)里把**扬声器输出**设为这个多输出设备

这样面试官的声音会同时送到你的耳机和 BlackHole,程序从 BlackHole 读音频。

### 3. Python 环境

需要 Python 3.10+。

```bash
cd interview_assistant
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

首次运行 faster-whisper 会下载 large-v3 模型(约 3GB),耐心等待。

## 运行

```bash
source venv/bin/activate
python main.py
```

启动后:

1. 悬浮窗右上角点 **⚙** 打开设置
2. **LLM 标签页**:选一个 provider,填对应 API key
3. **语音识别标签页**:默认用 faster-whisper 本地,如果要用阿里云就填 AppKey + Token
4. 确认后程序会自动重启音频 pipeline
5. 顶部 **ASR 按钮** 可以快速在 Whisper/阿里云之间切换

## 项目结构

```
interview_assistant/
├── main.py              # 入口 + 主循环,串联所有模块
├── config.py            # 配置加载/保存,默认配置
├── audio_capture.py     # 从 BlackHole 读音频流
├── asr.py               # ASR 双引擎(faster-whisper + 阿里云)
├── question_detector.py # 规则版问题检测
├── llm.py               # 四家云端 LLM 封装
├── ui.py                # PySide6 悬浮窗 + 设置面板
└── requirements.txt
```

## 配置文件

所有配置和 API key 存放在 `~/.interview_assistant/config.json`,纯本地,不会上传任何地方。

## 常见问题

**Q: 启动报 "找不到输入设备 BlackHole 2ch"?**
A: 确认已经 `brew install blackhole-2ch`,并在音频 MIDI 设置里创建了多输出设备。控制台会列出当前可用的输入设备供参考。

**Q: faster-whisper 下载很慢?**
A: 首次加载 large-v3 约 3GB。可以改 `config.json` 里的 `model` 为 `medium` 或 `small` 减小体积(准确率会下降)。

**Q: 答案延迟多少?**
A: ASR 2~3 秒 + LLM 2~3 秒,总延迟 4~6 秒是正常的。

**Q: 问题检测不准?**
A: 当前是规则版(问号 + 疑问词 + 静音超时)。如果漏判/误判多,可以调 `config.json` 里的 `silence_seconds` 和 `min_chars`,或者改成用 LLM 判断(需要改 `question_detector.py`)。

**Q: 阿里云 ASR 怎么申请 Token?**
A: 参考阿里云智能语音交互文档:https://help.aliyun.com/document_detail/84428.html ,开通服务后在控制台创建项目获取 AppKey,用 AccessKey 换取临时 Token。

## 提醒

这个工具的定位是**学习辅助和模拟面试复盘**。如果你打算在真实面试中实时使用,请自行评估:

- 面试官普遍知道这类工具存在,答题节奏和眼神的异常信号很明显
- 很多公司在面试协议里明确禁止使用未声明的 AI 辅助
- 靠工具拿到 offer 但能力对不上,试用期会很痛苦

更好的用法:面试前一周用它做模拟练习,把转写和 AI 点评认真看,针对弱项补。真正上场时工具可以开着做技术术语辅助,但不要依赖它的完整答案。

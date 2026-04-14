import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".interview_assistant" / "config.json"

DEFAULT_CONFIG = {
    "asr": {
        "engine": "faster_whisper",
        "faster_whisper": {
            "model": "large-v3",
            "device": "auto",
            "compute_type": "int8",
            "initial_prompt": "这是一场软件工程师技术面试,涉及 Python Java Go Kubernetes Docker Redis MySQL PostgreSQL gRPC Kafka RabbitMQ LLM RAG Transformer 分布式 微服务 高并发 缓存 消息队列 数据库 算法 系统设计."
        },
        "aliyun": {
            "app_key": "",
            "token": "",
            "url": "wss://nls-gateway.cn-shanghai.aliyuncs.com/ws/v1"
        }
    },
    "llm": {
        "provider": "claude",
        "claude":  {"api_key": "", "model": "claude-opus-4-5"},
        "openai":  {"api_key": "", "model": "gpt-4o"},
        "grok":    {"api_key": "", "model": "grok-2-latest"},
        "gemini":  {"api_key": "", "model": "gemini-2.0-flash"}
    },
    "audio": {
        "input_device_name": "BlackHole 2ch",
        "sample_rate": 16000,
        "chunk_seconds": 2.0
    },
    "question_detection": {
        "silence_seconds": 1.2,
        "min_chars": 6
    }
}


def load_config():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def merge(default, user):
        for k, v in default.items():
            if k not in user:
                user[k] = v
            elif isinstance(v, dict):
                merge(v, user[k])
        return user

    return merge(json.loads(json.dumps(DEFAULT_CONFIG)), cfg)


def save_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

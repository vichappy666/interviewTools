import json
import os
from pathlib import Path

import pymysql

CONFIG_PATH = Path.home() / ".interview_assistant" / "config.json"

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "interview_assistant",
}


def _load_keys_from_db():
    """从 MySQL 读取 API key"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cursor = conn.cursor()
        cursor.execute("SELECT `key`, `value` FROM config")
        keys = dict(cursor.fetchall())
        cursor.close()
        conn.close()
        return keys
    except Exception as e:
        print(f"[config] 从数据库读取 key 失败: {e}, 回退到本地配置")
        return {}

DEFAULT_CONFIG = {
    "asr": {
        "volcengine": {
            "app_key": "",
            "access_key": "",
            "resource_id": "volc.bigasr.sauc.duration"
        }
    },
    "llm": {
        "provider": "deepseek",
        "claude":  {"api_key": "", "model": "claude-haiku-4-5-20251001"},
        "openai":  {"api_key": "", "model": "gpt-5.4-nano"},
        "grok":    {"api_key": "", "model": "grok-4"},
        "gemini":  {"api_key": "", "model": "gemini-3-flash-preview"},
        "deepseek":{"api_key": "", "model": "deepseek-chat"}
    },
    "audio": {
        "input_device_name": "MacBook Pro麦克风",
        "sample_rate": 16000,
    },
    "question_detection": {
        "silence_seconds": 1.2,
        "min_chars": 6
    },
    "web": {
        "enabled": True,
        "host": "127.0.0.1",
        "port": 8765,
    }
}


def load_config():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

    def merge(default, user):
        result = {}
        all_keys = set(list(default.keys()) + list(user.keys()))
        for k in all_keys:
            d = default.get(k)
            u = user.get(k)
            if isinstance(d, dict) and isinstance(u, dict):
                result[k] = merge(d, u)
            elif d is not None and d != "":
                result[k] = d
            else:
                result[k] = u
        return result

    result = merge(json.loads(json.dumps(DEFAULT_CONFIG)), cfg)

    # 从 MySQL 读取 API key，覆盖空值
    db_keys = _load_keys_from_db()
    key_mapping = {
        "claude_api_key": ("llm", "claude", "api_key"),
        "openai_api_key": ("llm", "openai", "api_key"),
        "grok_api_key": ("llm", "grok", "api_key"),
        "gemini_api_key": ("llm", "gemini", "api_key"),
        "deepseek_api_key": ("llm", "deepseek", "api_key"),
        "volcengine_app_key": ("asr", "volcengine", "app_key"),
        "volcengine_access_key": ("asr", "volcengine", "access_key"),
    }
    for db_key, path in key_mapping.items():
        if db_key in db_keys and db_keys[db_key]:
            result[path[0]][path[1]][path[2]] = db_keys[db_key]

    # HF_TOKEN 设到环境变量
    if "hf_token" in db_keys and db_keys["hf_token"]:
        os.environ.setdefault("HF_TOKEN", db_keys["hf_token"])

    return result


def save_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

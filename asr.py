from abc import ABC, abstractmethod
import numpy as np


class ASREngine(ABC):
    @abstractmethod
    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str: ...


class FasterWhisperEngine(ASREngine):
    def __init__(self, cfg):
        from faster_whisper import WhisperModel
        print(f"[asr] 加载 faster-whisper: {cfg['model']} (首次运行会下载模型,请耐心等待)")
        self.model = WhisperModel(
            cfg["model"],
            device=cfg["device"],
            compute_type=cfg["compute_type"]
        )
        self.initial_prompt = cfg["initial_prompt"]
        print("[asr] faster-whisper 加载完成")

    def transcribe(self, audio, sample_rate):
        if audio is None or len(audio) == 0:
            return ""
        if np.abs(audio).mean() < 0.003:
            return ""
        segments, _ = self.model.transcribe(
            audio,
            language="zh",
            initial_prompt=self.initial_prompt,
            vad_filter=True,
            beam_size=5,
            condition_on_previous_text=False
        )
        return "".join(seg.text for seg in segments).strip()


class AliyunEngine(ASREngine):
    """
    阿里云一句话识别(非流式)。每个 chunk 单独调一次。
    要做真流式需要用 NlsSpeechTranscriber,先给能跑的版本。
    """
    def __init__(self, cfg):
        self.cfg = cfg
        if not cfg.get("app_key") or not cfg.get("token"):
            raise RuntimeError("阿里云 ASR 需要先在设置里填 app_key 和 token")
        try:
            import nls  # noqa
        except ImportError:
            raise RuntimeError("请先 pip install alibabacloud-nls-python-sdk")
        print("[asr] 阿里云 ASR 已就绪")

    def transcribe(self, audio, sample_rate):
        if audio is None or len(audio) == 0:
            return ""
        if np.abs(audio).mean() < 0.003:
            return ""
        import json
        import nls

        pcm = (audio * 32767).astype(np.int16).tobytes()
        result_text = []

        def on_completed(message, *args):
            try:
                data = json.loads(message)
                result_text.append(data.get("payload", {}).get("result", ""))
            except Exception:
                pass

        sr = nls.NlsSpeechRecognizer(
            url=self.cfg["url"],
            token=self.cfg["token"],
            appkey=self.cfg["app_key"],
            on_completed=on_completed
        )
        sr.start(aformat="pcm", sample_rate=sample_rate, enable_punctuation_prediction=True)
        step = 3200
        for i in range(0, len(pcm), step):
            sr.send_audio(pcm[i:i + step])
        sr.stop()
        return "".join(result_text).strip()


def build_asr(config):
    engine = config["asr"]["engine"]
    if engine == "faster_whisper":
        return FasterWhisperEngine(config["asr"]["faster_whisper"])
    elif engine == "aliyun":
        return AliyunEngine(config["asr"]["aliyun"])
    raise ValueError(f"未知 ASR 引擎: {engine}")

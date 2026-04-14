import sounddevice as sd
import queue


class AudioCapture:
    def __init__(self, device_name, sample_rate=16000, chunk_seconds=2.0):
        self.sample_rate = sample_rate
        self.chunk_size = int(sample_rate * chunk_seconds)
        self.device_index = self._find_device(device_name)
        self.queue = queue.Queue()
        self.stream = None

    def _find_device(self, name):
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if name.lower() in d["name"].lower() and d["max_input_channels"] > 0:
                return i
        available = "\n".join(
            f"  [{i}] {d['name']}" for i, d in enumerate(devices)
            if d["max_input_channels"] > 0
        )
        raise RuntimeError(
            f"找不到输入设备 '{name}'。请确认已安装 BlackHole 并在音频 MIDI 设置里配置好。\n"
            f"当前可用输入设备:\n{available}"
        )

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}")
        self.queue.put(indata[:, 0].copy())

    def start(self):
        self.stream = sd.InputStream(
            device=self.device_index,
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=self._callback,
            blocksize=self.chunk_size
        )
        self.stream.start()

    def stop(self):
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None

    def read_chunk(self, timeout=None):
        try:
            return self.queue.get(timeout=timeout)
        except queue.Empty:
            return None

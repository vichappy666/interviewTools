import sounddevice as sd


class AudioCapture:
    def __init__(self, device_name, sample_rate=16000, on_audio=None):
        self.sample_rate = sample_rate
        self.device_index = self._find_device(device_name)
        self.on_audio = on_audio
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
            f"找不到输入设备 '{name}'。\n当前可用输入设备:\n{available}"
        )

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}")
        if self.on_audio:
            self.on_audio(indata[:, 0].copy())

    def start(self):
        self.stream = sd.InputStream(
            device=self.device_index,
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            callback=self._callback,
            blocksize=1600,  # 100ms at 16kHz
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

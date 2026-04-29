/**
 * PCM Resampler AudioWorkletProcessor
 *
 * 从浏览器原生采样率（通常 48kHz，部分设备 44.1kHz）下取 mono Float32 PCM，
 * 用线性下采样算法重采样到 16kHz，转 Int16，每累计满 100ms（1600 samples = 3200 bytes）
 * 通过 port.postMessage 把 ArrayBuffer 推给主线程。
 *
 * 注意：
 *  - 这个文件 Vite 不会处理，必须放 public/ 下，运行时通过 /audio-worklet.js 加载
 *  - worklet scope 没有 module 系统，纯 JS，不能 import
 *  - sampleRate 是 worklet 全局变量（AudioContext 的采样率）
 */

class PCMResampler extends AudioWorkletProcessor {
  constructor() {
    super();
    // eslint-disable-next-line no-undef
    this.sourceRate = sampleRate; // worklet 全局：AudioContext.sampleRate
    this.targetRate = 16000;
    this.ratio = this.sourceRate / this.targetRate; // 例如 48000/16000 = 3
    this.frameSize = 1600; // 100ms @ 16kHz
    this.buffer = new Int16Array(this.frameSize);
    this.bufferPos = 0;
    this.resampleAcc = 0; // 浮点累加器，用于线性下采样取样位置
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const channel = input[0]; // mono：只取第一个声道
    if (!channel) return true;

    for (let i = 0; i < channel.length; i++) {
      this.resampleAcc += 1;
      if (this.resampleAcc >= this.ratio) {
        this.resampleAcc -= this.ratio;
        // Float32 [-1, 1] → Int16 [-32768, 32767]
        const sample = channel[i];
        const clipped = sample > 1 ? 1 : sample < -1 ? -1 : sample;
        this.buffer[this.bufferPos++] = clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff;
        if (this.bufferPos === this.frameSize) {
          // 拷贝一份独立 ArrayBuffer 推给主线程，避免下一帧覆盖
          this.port.postMessage(this.buffer.buffer.slice(0));
          this.bufferPos = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor('pcm-resampler', PCMResampler);

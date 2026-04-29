import { ref, type Ref } from 'vue'

/**
 * 麦克风权限 / 音频采集状态机
 *  - idle：未启动 / 已停止
 *  - requesting：正在请求权限 + 初始化
 *  - granted：已授权 + 采集中
 *  - denied：用户拒绝授权（终态，需要用户手动到浏览器设置开启）
 */
export type PermissionState = 'idle' | 'requesting' | 'granted' | 'denied'

export interface UseAudioCaptureReturn {
  /**
   * 开始采集。回调每 100ms 收到一帧 16kHz mono Int16 PCM（3200 bytes ArrayBuffer）。
   * 必须在用户手势（按钮 click 等）回调内调用，否则 iOS Safari 会拒绝。
   */
  start: (onFrame: (buf: ArrayBuffer) => void) => Promise<void>
  /** 停止采集 + 释放 mic。可重复调用。 */
  stop: () => void
  permissionState: Ref<PermissionState>
  /** 错误信息（中文友好提示），出错时由 start 抛出 + 写入这里供 UI 展示 */
  error: Ref<string | null>
}

/**
 * 浏览器麦克风采集 composable。
 *
 * 内部 pipeline:
 *   getUserMedia → MediaStreamAudioSourceNode → AudioWorkletNode(pcm-resampler)
 *     → port.onmessage(ArrayBuffer 3200 bytes) → onFrame
 *
 * 输出：16kHz mono Int16 PCM，每帧 100ms（与后端 ws.py 对齐）。
 */
export function useAudioCapture(): UseAudioCaptureReturn {
  const permissionState = ref<PermissionState>('idle')
  const error = ref<string | null>(null)

  let stream: MediaStream | null = null
  let audioContext: AudioContext | null = null
  let workletNode: AudioWorkletNode | null = null
  let sourceNode: MediaStreamAudioSourceNode | null = null

  function describeError(err: unknown): string {
    if (err instanceof Error) {
      if (err.name === 'NotAllowedError') return '麦克风权限被拒绝，请在浏览器设置中开启'
      if (err.name === 'NotFoundError') return '未检测到麦克风设备'
      if (err.name === 'NotReadableError') return '麦克风被其他应用占用'
      if (err.name === 'SecurityError') return '安全限制，请在 HTTPS 或 localhost 下使用'
      return err.message || '音频采集失败'
    }
    return '未知错误'
  }

  async function start(onFrame: (buf: ArrayBuffer) => void): Promise<void> {
    if (permissionState.value === 'granted') return // 已经在跑，幂等
    permissionState.value = 'requesting'
    error.value = null

    // 1. 申请麦克风权限
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
        video: false,
      })
    } catch (err) {
      permissionState.value = 'denied'
      error.value = describeError(err)
      throw err
    }

    // 2. 初始化 AudioContext + Worklet 管道
    try {
      audioContext = new AudioContext()
      await audioContext.audioWorklet.addModule('/audio-worklet.js')

      sourceNode = audioContext.createMediaStreamSource(stream)
      workletNode = new AudioWorkletNode(audioContext, 'pcm-resampler')

      workletNode.port.onmessage = (e: MessageEvent) => {
        if (e.data instanceof ArrayBuffer) {
          onFrame(e.data)
        }
      }

      // 注意：不连到 destination，否则会形成回声
      sourceNode.connect(workletNode)

      permissionState.value = 'granted'
    } catch (err) {
      stop()
      permissionState.value = 'idle'
      error.value = describeError(err)
      throw err
    }
  }

  function stop(): void {
    if (workletNode) {
      try {
        workletNode.port.onmessage = null
        workletNode.disconnect()
      } catch {
        /* ignore */
      }
      workletNode = null
    }
    if (sourceNode) {
      try {
        sourceNode.disconnect()
      } catch {
        /* ignore */
      }
      sourceNode = null
    }
    if (audioContext) {
      try {
        void audioContext.close()
      } catch {
        /* ignore */
      }
      audioContext = null
    }
    if (stream) {
      stream.getTracks().forEach((t) => t.stop())
      stream = null
    }
    // denied 是终态（用户拒绝过），保留以便 UI 持续展示提示
    if (permissionState.value !== 'denied') {
      permissionState.value = 'idle'
    }
  }

  return { start, stop, permissionState, error }
}

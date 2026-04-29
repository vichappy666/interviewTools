import { ref, type Ref } from 'vue'

/**
 * 麦克风权限 / 音频采集状态机
 *  - idle：未启动 / 已停止
 *  - requesting：正在请求权限 + 初始化
 *  - granted：已授权 + 采集中
 *  - denied：用户拒绝授权（终态，需要用户手动到浏览器设置开启）
 */
export type PermissionState = 'idle' | 'requesting' | 'granted' | 'denied'

/**
 * 音频源模式：
 *  - 'mic'    仅麦克风（默认，所有浏览器可用）
 *  - 'tab'    仅系统音频（getDisplayMedia 共享浏览器标签页拿其音轨）
 *  - 'mixed'  麦克风 + 系统音频混合（两路 source 合并到同一个 worklet）
 */
export type AudioSourceMode = 'mic' | 'tab' | 'mixed'

export interface UseAudioCaptureReturn {
  /**
   * 开始采集。回调每 100ms 收到一帧 16kHz mono Int16 PCM（3200 bytes ArrayBuffer）。
   * 必须在用户手势（按钮 click 等）回调内调用，否则 iOS Safari 会拒绝。
   * @param onFrame 每帧回调
   * @param mode    音频源模式，默认 'mic'
   */
  start: (onFrame: (buf: ArrayBuffer) => void, mode?: AudioSourceMode) => Promise<void>
  /** 停止采集 + 释放所有 stream。可重复调用。 */
  stop: () => void
  permissionState: Ref<PermissionState>
  /** 错误信息（中文友好提示），出错时由 start 抛出 + 写入这里供 UI 展示 */
  error: Ref<string | null>
}

/**
 * 浏览器音频采集 composable，支持麦克风 / 系统音频 / 混合 三种模式。
 *
 * 内部 pipeline:
 *   getUserMedia / getDisplayMedia → MediaStreamAudioSourceNode
 *     → AudioWorkletNode(pcm-resampler，强制下混到 mono)
 *     → port.onmessage(ArrayBuffer 3200 bytes) → onFrame
 *
 * 输出：16kHz mono Int16 PCM，每帧 100ms（与后端 ws.py 对齐）。
 *
 * 注意：
 *  - mixed 模式下两路 source 都 connect 到同一个 workletNode，WebAudio 会自动相加；
 *    workletNode 用 channelCount=1, channelCountMode='explicit' 强制下混到 mono。
 *  - tab/mixed 必须 getDisplayMedia({video:true,audio:true})；Chrome 不允许只要 audio。
 *  - 若用户在 Chrome 共享窗口里没勾"分享标签页音频"，audio track 数为 0，明确报错。
 *  - 若分享中途用户从浏览器栏点"停止分享"：tab 模式整体停；mixed 模式静默降级到只剩麦克风。
 */
export function useAudioCapture(): UseAudioCaptureReturn {
  const permissionState = ref<PermissionState>('idle')
  const error = ref<string | null>(null)

  let micStream: MediaStream | null = null
  let tabStream: MediaStream | null = null
  let audioContext: AudioContext | null = null
  let workletNode: AudioWorkletNode | null = null
  let micSource: MediaStreamAudioSourceNode | null = null
  let tabSource: MediaStreamAudioSourceNode | null = null

  function describeError(err: unknown, ctx: 'mic' | 'tab' = 'mic'): string {
    if (err instanceof Error) {
      if (err.name === 'NotAllowedError') {
        return ctx === 'tab' ? '已取消屏幕共享' : '麦克风权限被拒绝，请在浏览器设置中开启'
      }
      if (err.name === 'NotFoundError') return '未检测到麦克风设备'
      if (err.name === 'NotReadableError') return '麦克风被其他应用占用'
      if (err.name === 'SecurityError') return '安全限制，请在 HTTPS 或 localhost 下使用'
      return err.message || '音频采集失败'
    }
    return '未知错误'
  }

  async function start(
    onFrame: (buf: ArrayBuffer) => void,
    mode: AudioSourceMode = 'mic',
  ): Promise<void> {
    if (permissionState.value === 'granted') return // 已经在跑，幂等
    permissionState.value = 'requesting'
    error.value = null

    // 1. 申请麦克风（mic / mixed）
    if (mode === 'mic' || mode === 'mixed') {
      try {
        micStream = await navigator.mediaDevices.getUserMedia({
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
        error.value = describeError(err, 'mic')
        throw err
      }
    }

    // 2. 申请系统音频（tab / mixed）
    if (mode === 'tab' || mode === 'mixed') {
      if (!navigator.mediaDevices.getDisplayMedia) {
        stop()
        permissionState.value = 'idle'
        error.value = '当前浏览器不支持系统音频共享，请改用 Chrome'
        throw new Error('getDisplayMedia not supported')
      }
      try {
        // Chrome 强制要求 video:true 才会弹分享框；我们只用 audio
        tabStream = await navigator.mediaDevices.getDisplayMedia({
          video: true,
          audio: true,
        })
      } catch (err) {
        stop()
        permissionState.value = 'idle'
        error.value = describeError(err, 'tab')
        throw err
      }
      if (tabStream.getAudioTracks().length === 0) {
        // 用户共享了但没勾"分享标签页音频"
        tabStream.getTracks().forEach((t) => t.stop())
        tabStream = null
        stop()
        permissionState.value = 'idle'
        error.value = '需要勾选"同时分享标签页音频"。请重试，并在分享对话框底部勾上该选项'
        throw new Error('no audio track in displayMedia')
      }
      // 视频轨我们不需要，立即停掉省资源（音频轨保持）
      tabStream.getVideoTracks().forEach((t) => t.stop())
      // 监听用户从 Chrome 工具栏点"停止分享"
      const audioTrack = tabStream.getAudioTracks()[0]
      audioTrack.onended = () => {
        if (!tabStream) return
        if (mode === 'tab') {
          // 仅系统音频模式 → 整体停止
          error.value = '已停止屏幕共享'
          stop()
        } else {
          // mixed 模式 → 静默降级到 mic only
          if (tabSource) {
            try {
              tabSource.disconnect()
            } catch {
              /* ignore */
            }
            tabSource = null
          }
          tabStream.getTracks().forEach((t) => t.stop())
          tabStream = null
          error.value = '系统音频已停止，仅麦克风继续'
        }
      }
    }

    // 3. 初始化 AudioContext + Worklet 管道
    try {
      audioContext = new AudioContext()
      await audioContext.audioWorklet.addModule('/audio-worklet.js')

      // 强制下混到 mono：mixed 模式下两路 source 相加可能为 stereo，
      // explicit + channelCount:1 会按"speakers"规则做 L+R→mono
      workletNode = new AudioWorkletNode(audioContext, 'pcm-resampler', {
        channelCount: 1,
        channelCountMode: 'explicit',
        channelInterpretation: 'speakers',
      })

      workletNode.port.onmessage = (e: MessageEvent) => {
        if (e.data instanceof ArrayBuffer) {
          onFrame(e.data)
        }
      }

      if (micStream) {
        micSource = audioContext.createMediaStreamSource(micStream)
        micSource.connect(workletNode)
      }
      if (tabStream) {
        tabSource = audioContext.createMediaStreamSource(tabStream)
        tabSource.connect(workletNode)
      }

      // 注意：不连到 destination，否则会形成回声

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
    if (micSource) {
      try {
        micSource.disconnect()
      } catch {
        /* ignore */
      }
      micSource = null
    }
    if (tabSource) {
      try {
        tabSource.disconnect()
      } catch {
        /* ignore */
      }
      tabSource = null
    }
    if (audioContext) {
      try {
        void audioContext.close()
      } catch {
        /* ignore */
      }
      audioContext = null
    }
    if (micStream) {
      micStream.getTracks().forEach((t) => t.stop())
      micStream = null
    }
    if (tabStream) {
      tabStream.getTracks().forEach((t) => t.stop())
      tabStream = null
    }
    // denied 是终态（用户拒绝过），保留以便 UI 持续展示提示
    if (permissionState.value !== 'denied') {
      permissionState.value = 'idle'
    }
  }

  return { start, stop, permissionState, error }
}

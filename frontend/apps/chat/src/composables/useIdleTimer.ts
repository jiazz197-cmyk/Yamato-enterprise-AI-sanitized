import { onUnmounted } from 'vue'

const ACTIVITY_EVENTS = [
  'mousemove',
  'mousedown',
  'keydown',
  'scroll',
  'touchstart',
  'click',
] as const

/**
 * 用户空闲检测 composable
 *
 * 监听常见用户操作事件，若在 timeoutMs 毫秒内无任何操作则调用 onIdle。
 * 对外暴露 start() / stop()，由调用方决定启停时机。
 * 组件卸载时自动 stop() 防止内存泄漏。
 */
export function useIdleTimer(timeoutMs: number, onIdle: () => void) {
  let timer: ReturnType<typeof setTimeout> | null = null

  const reset = () => {
    if (timer !== null) clearTimeout(timer)
    timer = setTimeout(onIdle, timeoutMs)
  }

  const start = () => {
    reset()
    ACTIVITY_EVENTS.forEach((e) =>
      document.addEventListener(e, reset, { passive: true })
    )
  }

  const stop = () => {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
    ACTIVITY_EVENTS.forEach((e) => document.removeEventListener(e, reset))
  }

  onUnmounted(stop)

  return { start, stop }
}

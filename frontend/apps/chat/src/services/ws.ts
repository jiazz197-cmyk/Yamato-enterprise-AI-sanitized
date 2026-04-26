import { config } from '../config'
import { getAuthTokenFromStorage } from './token_storage'

const toWsBase = (apiBaseUrl: string): string => {
  if (apiBaseUrl.startsWith('http://') || apiBaseUrl.startsWith('https://')) {
    const url = new URL(apiBaseUrl)
    const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${url.host}${url.pathname.replace(/\/$/, '')}`
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const path = apiBaseUrl.startsWith('/') ? apiBaseUrl : `/${apiBaseUrl}`
  return `${protocol}//${window.location.host}${path.replace(/\/$/, '')}`
}

export interface TaskWsCallbacks {
  onOpen?: () => void
  onMessage?: (payload: unknown) => void
  onError?: () => void
  onClose?: () => void
}

export const createTaskWebSocket = (taskId: string, callbacks?: TaskWsCallbacks): WebSocket => {
  const token = getAuthTokenFromStorage()
  if (!token) {
    throw new Error('未登录或登录态已失效，请重新登录')
  }

  const base = toWsBase(config.apiBaseUrl)
  const wsUrl = `${base}/document-tasks/ws/${encodeURIComponent(taskId)}?token=${encodeURIComponent(token)}`
  const socket = new WebSocket(wsUrl)

  socket.onopen = () => {
    callbacks?.onOpen?.()
  }

  socket.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data) as unknown
      callbacks?.onMessage?.(payload)
    } catch {
      callbacks?.onMessage?.(event.data)
    }
  }

  socket.onerror = () => {
    callbacks?.onError?.()
  }

  socket.onclose = () => {
    callbacks?.onClose?.()
  }

  return socket
}


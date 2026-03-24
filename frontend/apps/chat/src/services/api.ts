import { config } from '../config'
import type { ApiError } from '../types/chat'

const handleUnauthorized = (): void => {
  try {
    localStorage.removeItem(config.authTokenStorageKey)
    localStorage.removeItem(config.settingsStorageKey)
  } catch {
    // ignore storage errors
  }

  if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
    window.location.href = '/login'
  }
}

const getAuthToken = (): string | null => {
  try {
    const token = localStorage.getItem(config.authTokenStorageKey)
    return token || null
  } catch {
    return null
  }
}

/**
 * 创建标准请求头
 * 聊天接口使用 Chat API Key
 */
export const createChatHeaders = (): HeadersInit => {
  return {
    Authorization: `Bearer ${config.chatApiKey}`,
    'Content-Type': 'application/json',
  }
}

/**
 * 创建业务接口请求头
 * 仅允许使用登录态 Token，禁止回退到 Chat API Key
 */
export const createHeaders = (): HeadersInit => {
  const token = getAuthToken()
  if (!token) {
    throw new Error('未登录或登录态已失效，请重新登录')
  }

  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
  }
}

/**
 * 处理 API 错误响应
 */
export const handleApiError = async (response: Response): Promise<never> => {
  let error: ApiError

  try {
    const payload = await response.json()
    error = {
      code: String((payload as { code?: unknown })?.code ?? 'api_error'),
      message: String((payload as { message?: unknown; detail?: unknown })?.message ?? (payload as { detail?: unknown })?.detail ?? '请求失败'),
      status: response.status,
    }
  } catch {
    error = {
      code: 'unknown_error',
      message: '网络请求失败',
      status: response.status,
    }
  }

  if (response.status === 401) {
    handleUnauthorized()
    throw {
      ...error,
      message: '登录已过期，请重新登录',
    } as ApiError
  }

  throw error
}

/**
 * 通用 API 请求方法
 */
export const apiRequest = async <T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> => {
  const url = `${config.apiBaseUrl}${endpoint}`
  
  const response = await fetch(url, {
    ...options,
    headers: {
      ...createHeaders(),
      ...options?.headers,
    },
  })
  
  if (!response.ok) {
    await handleApiError(response)
  }
  
  return response.json()
}

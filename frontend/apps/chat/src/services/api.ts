import { config } from '../config'
import type { ApiError } from '../types/chat'
import { clearAuthTokenFromStorage, getAuthTokenFromStorage } from './token_storage'

const handleUnauthorized = (): void => {
  clearAuthTokenFromStorage()
  try {
    localStorage.removeItem(config.settingsStorageKey)
  } catch {
    // 本地存储不可用则忽略
  }

  if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
    window.location.href = '/login'
  }
}

const getAuthToken = (): string | null => {
  return getAuthTokenFromStorage()
}

/** 聊天走代理时只带 JSON，鉴权在网关处理。 */
export const createChatHeaders = (): HeadersInit => {
  return {
    'Content-Type': 'application/json',
  }
}

/** 业务 API：Bearer 来自登录，不用 Chat API Key。 */
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

  const isLoginRequest = response.url.includes(config.loginEndpoint)

  if (response.status === 401) {
    if (!isLoginRequest) {
      handleUnauthorized()
      throw {
        ...error,
        message: '登录已过期，请重新登录',
      } as ApiError
    }
  }

  throw error
}

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

  if (response.status === 204 || response.status === 205) {
    return undefined as T
  }

  const contentLength = response.headers.get('content-length')
  if (contentLength === '0') {
    return undefined as T
  }

  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('application/json')) {
    return undefined as T
  }
  
  return response.json()
}

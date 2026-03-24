import { config } from '../config'
import type { ApiError } from '../types/chat'

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
    error = await response.json()
  } catch {
    error = {
      code: 'unknown_error',
      message: '网络请求失败',
      status: response.status,
    }
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

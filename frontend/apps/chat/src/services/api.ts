import { config } from '../config'
import type { ApiError } from '../types/chat'

/**
 * 创建标准请求头
 */
export const createHeaders = (): HeadersInit => {
  return {
    'Authorization': `Bearer ${config.chatApiKey}`,
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

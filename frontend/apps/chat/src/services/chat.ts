import { config } from '../config'
import { createHeaders } from './api'
import type {
  ChatMessageRequest,
  SSEEvent,
  Conversation,
  ConversationsResponse,
  MessagesResponse,
  RenameConversationRequest,
} from '../types/chat'

/**
 * SSE 事件回调类型
 */
export interface SSECallbacks {
  onMessage?: (content: string, data: SSEEvent) => void
  onEnd?: (data: SSEEvent) => void
  onError?: (error: Error) => void
}

/**
 * 发送聊天消息（SSE 流式响应）
 */
export const sendChatMessage = async (
  query: string,
  conversationId: string | undefined,
  callbacks: SSECallbacks
): Promise<{ taskId: string; conversationId: string }> => {
  const url = `${config.apiBaseUrl}/chat-messages`
  
  const requestBody: ChatMessageRequest = {
    query,
    user: 'user', // 暂定为 user，后续会加上用户管理功能
    conversation_id: conversationId,
    response_mode: 'streaming',
  }
  
  const response = await fetch(url, {
    method: 'POST',
    headers: createHeaders(),
    body: JSON.stringify(requestBody),
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.message || '发送消息失败')
  }
  
  const reader = response.body?.getReader()
  const decoder = new TextDecoder()
  
  if (!reader) {
    throw new Error('无法读取响应流')
  }
  
  let taskId = ''
  let responseConversationId = ''
  
  try {
    while (true) {
      const { done, value } = await reader.read()
      
      if (done) break
      
      const chunk = decoder.decode(value, { stream: true })
      const lines = chunk.split('\n')
      
      for (const line of lines) {
        if (!line.trim() || !line.startsWith('data: ')) continue
        
        const dataStr = line.substring(6) // 移除 'data: ' 前缀
        
        try {
          const data = JSON.parse(dataStr) as SSEEvent
          
          // 保存 task_id 和 conversation_id
          if ('task_id' in data) {
            taskId = data.task_id
          }
          if ('conversation_id' in data) {
            responseConversationId = data.conversation_id
          }
          
          // 处理不同类型的事件
          if (data.event === 'message' || data.event === 'agent_message') {
            callbacks.onMessage?.(data.answer, data)
          } else if (data.event === 'message_end') {
            callbacks.onEnd?.(data)
          } else if (data.event === 'error') {
            callbacks.onError?.(new Error(data.message))
          }
        } catch (error) {
          // 忽略无法解析的行（可能是 ping 事件等）
          if (import.meta.env.DEV) {
            console.warn('Failed to parse SSE data:', dataStr, error)
          }
        }
      }
    }
  } catch (error) {
    callbacks.onError?.(error as Error)
    throw error
  } finally {
    reader.releaseLock()
  }
  
  return {
    taskId,
    conversationId: responseConversationId || conversationId || '',
  }
}

/**
 * 停止消息生成
 */
export const stopChatMessage = async (taskId: string): Promise<void> => {
  const url = `${config.apiBaseUrl}/chat-messages/${taskId}/stop`
  
  const response = await fetch(url, {
    method: 'POST',
    headers: createHeaders(),
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.message || '停止消息生成失败')
  }
}

/**
 * 获取会话列表
 */
export const getConversations = async (
  page = 1,
  limit = 20
): Promise<ConversationsResponse> => {
  const url = `${config.apiBaseUrl}/conversations?user=user&page=${page}&limit=${limit}`
  
  const response = await fetch(url, {
    method: 'GET',
    headers: createHeaders(),
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.message || '获取会话列表失败')
  }
  
  return response.json()
}

/**
 * 获取消息列表
 */
export const getMessages = async (
  conversationId: string,
  page = 1,
  limit = 20
): Promise<MessagesResponse> => {
  const url = `${config.apiBaseUrl}/messages?user=user&conversation_id=${conversationId}&page=${page}&limit=${limit}`
  
  const response = await fetch(url, {
    method: 'GET',
    headers: createHeaders(),
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.message || '获取消息列表失败')
  }
  
  return response.json()
}

/**
 * 重命名会话
 */
export const renameConversation = async (
  conversationId: string,
  name: string,
  autoGenerate = false
): Promise<Conversation> => {
  const url = `${config.apiBaseUrl}/conversations/${conversationId}/name`
  
  const requestBody: RenameConversationRequest = {
    name,
    auto_generate: autoGenerate,
  }
  
  const response = await fetch(url, {
    method: 'POST',
    headers: createHeaders(),
    body: JSON.stringify(requestBody),
  })
  
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.message || '重命名会话失败')
  }
  
  return response.json()
}

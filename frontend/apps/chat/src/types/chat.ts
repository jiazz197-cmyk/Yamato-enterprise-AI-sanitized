/**
 * Dify API 类型定义
 */

// 消息角色
export type MessageRole = 'user' | 'assistant'

// 消息对象
export interface Message {
  id?: string
  role: MessageRole
  content: string
  timestamp?: string
  conversationId?: string
}

// 会话对象
export interface Conversation {
  id: string
  name: string
  inputs: Record<string, unknown>
  status: string
  introduction: string
  created_at: number
  updated_at: number
}

// 搜索模式
export type SearchMode = '联网搜索' | '本地检索' | '本地&网络'

// 发送消息请求参数
export interface ChatMessageRequest {
  user: string
  user_id: string
  search: SearchMode
  query: string
  inputs: Record<string, unknown>
  conversation_id?: string
  response_mode: 'streaming' | 'blocking'
}

// SSE 事件类型
export type SSEEventType = 
  | 'message' 
  | 'agent_message'
  | 'agent_thought'
  | 'message_file'
  | 'message_end'
  | 'message_replace'
  | 'error'
  | 'ping'

// SSE 消息事件
export interface SSEMessageEvent {
  event: 'message' | 'agent_message' | 'message_replace'
  task_id: string
  id: string
  conversation_id: string
  answer: string
  created_at: number
}

export interface SSEAgentThoughtEvent {
  event: 'agent_thought'
  task_id: string
  id?: string
  conversation_id?: string
  thought?: string
  message?: string
  answer?: string
  created_at?: number
}

// SSE 消息结束事件
export interface SSEMessageEndEvent {
  event: 'message_end'
  task_id: string
  id: string
  conversation_id: string
  metadata: {
    usage: {
      prompt_tokens: number
      completion_tokens: number
      total_tokens: number
    }
    retriever_resources?: unknown[]
  }
}

// SSE 错误事件
export interface SSEErrorEvent {
  event: 'error'
  task_id: string
  code: string
  message: string
  status: number
}

// SSE 事件联合类型
export type SSEEvent = SSEMessageEvent | SSEAgentThoughtEvent | SSEMessageEndEvent | SSEErrorEvent

// 获取会话列表响应
export interface ConversationsResponse {
  data: Conversation[]
  has_more: boolean
  limit: number
  page: number
}

// 获取消息列表响应
export interface MessagesResponse {
  data: Message[]
  has_more: boolean
  limit: number
}

// 重命名会话请求
export interface RenameConversationRequest {
  name: string
  auto_generate?: boolean
}

// API 错误响应
export interface ApiError {
  code: string
  message: string
  status: number
}

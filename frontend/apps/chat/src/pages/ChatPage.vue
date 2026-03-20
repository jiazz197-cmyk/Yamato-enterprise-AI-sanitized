<template>
  <div class="chat-page">
    <PageHeader title="AI" subtitle="与 AI 助手对话" />

    <div class="chat-body">
      <MessageList
        ref="historyMessageListRef"
        variant="history"
        :class="{ 'chat-history-panel--collapsed': historyCollapsed }"
        :history-items="chatHistory"
        :active-item-id="currentConversationId"
        :editing-item-id="editingChatId"
        :editing-title="editingChatTitle"
        :rename-api-base-url="config.apiBaseUrl"
        :rename-api-token="config.chatApiKey"
        :rename-user="chatSettings.user"
        :delete-api-base-url="config.apiBaseUrl"
        :delete-api-token="config.chatApiKey"
        :delete-user="chatSettings.user"
        @update:editingTitle="editingChatTitle = $event"
        @create="createNewChat"
        @select="loadChat"
        @rename-start="renameChat"
        @rename-save="saveRename"
        @rename-cancel="cancelRename"
        @rename-error="handleRenameError"
        @archive="archiveChat"
        @delete="deleteChat"
      >
        <template #history-actions>
          <ChatSummaryAction @click="openSummaryDialog" />
        </template>
      </MessageList>

      <button
        class="chat-history-toggle"
        :class="{ 'chat-history-toggle--collapsed': historyCollapsed }"
        type="button"
        :aria-expanded="!historyCollapsed"
        @click="toggleHistory"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path
            d="M15 18l-6-6 6-6"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>

      <div class="chat-main">
        <div ref="messageListRef" class="message-list-container">
          <MessageList>
            <MessageItem
              v-for="(message, index) in messages"
              :key="index"
              :role="message.role"
              :content="message.content"
              :timestamp="message.role === 'user' ? message.timestamp : undefined"
              assistant-avatar-url="/ai_icon.png"
            />
            <div v-if="isLoading" class="loading-indicator">
              <div class="loading-dots">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          </MessageList>
        </div>

          <div class="chat-input-container">
            <div class="chat-input-wrapper">
                <Input
                  v-model="inputMessage"
                  class="chat-input"
                  placeholder="输入消息..."
                  multiline
                  :rows="1"
                  @enter="sendMessage"
                />

                <div class="chat-input-overlay chat-input-overlay--left">
                  <div ref="searchDropdownRef" class="search-mode-dropdown">
                    <button class="search-mode-btn" type="button" @click.stop="toggleSearchDropdown">
                      <span class="search-mode-label">{{ searchModeLabel }}</span>
                      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <path
                          d="M6 9l6 6 6-6"
                          stroke="currentColor"
                          stroke-width="2.5"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                        />
                      </svg>
                    </button>
                  </div>

                  <button
                    class="knowledge-upload-btn"
                    type="button"
                    :disabled="isUploadingKnowledge"
                    @click.stop="openKnowledgeUpload"
                  >
                    {{ isUploadingKnowledge ? '上传中...' : '知识上传' }}
                  </button>

                  <input
                    ref="knowledgeUploadInputRef"
                    class="knowledge-upload-input"
                    type="file"
                    multiple
                    @change="handleKnowledgeUploadChange"
                  />
                </div>

                <div class="chat-input-overlay chat-input-overlay--right">
                  <button
                    class="chat-send-btn"
                    :class="{ 'chat-send-btn--stop': isLoading }"
                    :disabled="!isLoading && !inputMessage.trim()"
                    type="button"
                    @click="isLoading ? stopGeneration() : sendMessage()"
                  >
                    <svg v-if="!isLoading" width="20" height="20" viewBox="0 0 24 24" fill="none">
                      <path
                        d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"
                        stroke="currentColor"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      />
                    </svg>
                    <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none">
                      <rect
                        x="6"
                        y="6"
                        width="12"
                        height="12"
                        rx="1"
                        fill="currentColor"
                      />
                    </svg>
                  </button>
                </div>
              </div>

              <Teleport to="body">
                <div
                  v-if="showSearchDropdown"
                  class="search-mode-menu"
                  :style="searchDropdownStyle"
                  @click.stop
                >
                  <button
                    class="search-mode-item"
                    :class="{ 'search-mode-item--active': chatSettings.search === '联网搜索' }"
                    type="button"
                    @click="setSearchMode('联网搜索')"
                  >联网搜索</button>
                  <button
                    class="search-mode-item"
                    :class="{ 'search-mode-item--active': chatSettings.search === '本地检索' }"
                    type="button"
                    @click="setSearchMode('本地检索')"
                  >本地检索</button>
                  <button
                    class="search-mode-item"
                    :class="{ 'search-mode-item--active': chatSettings.search === '本地&网络' }"
                    type="button"
                    @click="setSearchMode('本地&网络')"
                  >本地&amp;网络</button>
                </div>
              </Teleport>
              <p class="chat-input-hint">AI 可能会出错，请验证重要信息</p>
        </div>
      </div>
    </div>

    <ConfirmDialog
      v-model="showDeleteDialog"
      title="删除对话"
      message="确定要删除这个对话吗？此操作无法撤销。"
      type="danger"
      confirm-text="删除"
      cancel-text="取消"
      @confirm="confirmDelete"
    />

    <ChatSummaryDialog
      v-model="showSummaryDialog"
      :user-id="summaryUserId"
      :api-base-url="config.apiBaseUrl"
      :api-token="config.chatApiKey"
    />

  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import {
  PageHeader,
  MessageList,
  MessageItem,
  ConfirmDialog,
  ChatSummaryAction,
  ChatSummaryDialog,
  Input,
  useToast,
  useChatSummary,
} from '@yamato/components'
import { config } from '../config'
import { sendChatMessage, getConversations, getMessages, stopChatMessage } from '../services/chat'
import type { Conversation, SearchMode } from '../types/chat'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp?: string
}

interface ChatHistoryItem {
  id: string
  title: string
}

interface ChatSettings {
  user: string
  search: SearchMode
}

interface BackendMessageRecord {
  role?: string
  content?: string
  query?: string
  answer?: string
  created_at?: number
}

const inputMessage = ref('')
const messages = ref<Message[]>([])
const isLoading = ref(false)
const messageListRef = ref<HTMLElement | null>(null)
const historyMessageListRef = ref<{ deleteConversation: (chatId: string) => Promise<boolean> } | null>(null)
const historyCollapsed = ref(false)
const showDeleteDialog = ref(false)
const chatToDelete = ref<string | null>(null)
const editingChatId = ref<string | null>(null)
const editingChatTitle = ref('')
const showSummaryDialog = ref(false)
const chatHistory = ref<ChatHistoryItem[]>([
  {
    id: '1',
    title: '新对话',
  },
])
const currentConversationId = ref<string | undefined>(undefined)
const currentTaskId = ref<string | undefined>(undefined)

const SETTINGS_STORAGE_KEY = 'yamato_chat_settings'
const chatSettings = ref<ChatSettings>({ user: '', search: '联网搜索' })

type CachedChatSettings = {
  user?: string | number
  search?: SearchMode
}

const SEARCH_MODE_VALUES: SearchMode[] = ['联网搜索', '本地检索', '本地&网络']

const isSearchMode = (value: unknown): value is SearchMode => {
  return typeof value === 'string' && SEARCH_MODE_VALUES.includes(value as SearchMode)
}

const getErrorMessage = (error: unknown, fallback: string): string => {
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallback
}

const showSearchDropdown = ref(false)
const searchDropdownRef = ref<HTMLElement | null>(null)
const searchDropdownStyle = ref<Record<string, string>>({ top: '0px', left: '0px' })

const searchModeLabel = computed(() => {
  return chatSettings.value.search
})

const summaryUserId = computed(() => {
  return String(chatSettings.value.user ?? '').trim() || 'user'
})

const { showSuccess, showError } = useToast()
const { archiveConversation } = useChatSummary({
  apiBaseUrl: config.apiBaseUrl,
  apiToken: config.chatApiKey,
})

let streamingAbortController: AbortController | null = null
const knowledgeUploadInputRef = ref<HTMLInputElement | null>(null)
const isUploadingKnowledge = ref(false)
const activeKnowledgeTaskId = ref<string | null>(null)
let knowledgeStatusPollTimer: number | null = null

const saveCachedSettings = () => {
  try {
    localStorage.setItem(
      SETTINGS_STORAGE_KEY,
      JSON.stringify({
        user: chatSettings.value.user,
        search: chatSettings.value.search,
      })
    )
  } catch {
    // ignore
  }
}

const loadCachedSettings = () => {
  try {
    const cached = localStorage.getItem(SETTINGS_STORAGE_KEY)
    if (cached) {
      const parsed = JSON.parse(cached) as CachedChatSettings
      chatSettings.value = {
        user: String(parsed.user ?? ''),
        search: isSearchMode(parsed.search) ? parsed.search : '联网搜索',
      }
    }
  } catch {
    // ignore
  }
}

const toggleSearchDropdown = () => {
  if (showSearchDropdown.value) {
    showSearchDropdown.value = false
    return
  }
  const el = searchDropdownRef.value
  if (el) {
    const rect = el.getBoundingClientRect()
    searchDropdownStyle.value = {
      top: `${rect.bottom + 6}px`,
      left: `${rect.left}px`,
    }
  }
  showSearchDropdown.value = true
}

const setSearchMode = (mode: SearchMode) => {
  chatSettings.value.search = mode
  showSearchDropdown.value = false
  saveCachedSettings()
}

const openKnowledgeUpload = () => {
  if (isUploadingKnowledge.value) {
    return
  }
  knowledgeUploadInputRef.value?.click()
}

const getUploadAuthorization = (): string => {
  try {
    const token = localStorage.getItem(config.authTokenStorageKey)
    if (token) {
      return `Bearer ${token}`
    }
  } catch {
    // ignore
  }
  return `Bearer ${config.chatApiKey}`
}

const clearKnowledgeTaskPolling = () => {
  if (knowledgeStatusPollTimer !== null) {
    window.clearTimeout(knowledgeStatusPollTimer)
    knowledgeStatusPollTimer = null
  }
}

const finishKnowledgeTask = () => {
  clearKnowledgeTaskPolling()
  activeKnowledgeTaskId.value = null
  isUploadingKnowledge.value = false
}

const pollKnowledgeTaskStatus = async (taskId: string) => {
  try {
    const response = await fetch(`${config.apiBaseUrl}/docs/status/${encodeURIComponent(taskId)}`, {
      method: 'GET',
      headers: {
        Authorization: getUploadAuthorization(),
      },
    })

    if (!response.ok) {
      throw new Error('知识上传状态查询失败')
    }

    const result = (await response.json()) as {
      status?: string
      progress?: number
      message?: string
      error?: string
    }

    const status = String(result.status ?? '').toLowerCase()

    if (status === 'completed') {
      showSuccess('知识上传处理完成')
      finishKnowledgeTask()
      return
    }

    if (status === 'failed' || status === 'cancelled') {
      showError(result.error || result.message || '知识上传处理失败')
      finishKnowledgeTask()
      return
    }

    knowledgeStatusPollTimer = window.setTimeout(() => {
      void pollKnowledgeTaskStatus(taskId)
    }, 1500)
  } catch (error: unknown) {
    showError(getErrorMessage(error, '知识上传状态查询失败'))
    finishKnowledgeTask()
  }
}

const handleKnowledgeUploadChange = async (event: Event) => {
  const target = event.target as HTMLInputElement
  const selectedFiles = target.files ? Array.from(target.files) : []

  if (selectedFiles.length === 0 || isUploadingKnowledge.value) {
    return
  }

  const formData = new FormData()
  for (const file of selectedFiles) {
    formData.append('files', file)
  }

  const uploader = String(chatSettings.value.user ?? '').trim() || 'user'

  let keepUploadingState = false
  isUploadingKnowledge.value = true

  try {
    const query = new URLSearchParams({
      instance_id: '2',
      uploader,
    })

    const response = await fetch(`${config.apiBaseUrl}/docs/process?${query.toString()}`, {
      method: 'POST',
      headers: {
        Authorization: getUploadAuthorization(),
      },
      body: formData,
    })

    if (!response.ok) {
      const errorPayload = (await response.json().catch(() => null)) as
        | { detail?: string; message?: string }
        | null
      const message = errorPayload?.detail || errorPayload?.message || '知识上传失败'
      throw new Error(message)
    }

    const result = (await response.json()) as { task_id?: string; files_count?: number }
    const uploadedCount = result.files_count ?? selectedFiles.length
    const taskId = typeof result.task_id === 'string' ? result.task_id.trim() : ''

    showSuccess(`知识上传任务已创建（${uploadedCount} 个文件）`)

    if (taskId) {
      keepUploadingState = true
      activeKnowledgeTaskId.value = taskId
      clearKnowledgeTaskPolling()
      void pollKnowledgeTaskStatus(taskId)
    }
  } catch (error: unknown) {
    showError(getErrorMessage(error, '知识上传失败'))
  } finally {
    if (!keepUploadingState) {
      isUploadingKnowledge.value = false
    }
    target.value = ''
  }
}

const formatTime = (): string => {
  const now = new Date()
  return now.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

const buildConversationTitle = (text: string): string => {
  const trimmed = text.trim().replace(/\s+/g, ' ')
  if (!trimmed) {
    return '新对话'
  }
  return trimmed.length > 24 ? `${trimmed.slice(0, 24)}...` : trimmed
}

const upsertChatHistoryToTop = (chatId: string, title?: string) => {
  const index = chatHistory.value.findIndex((chat) => chat.id === chatId)

  if (index === -1) {
    chatHistory.value.unshift({
      id: chatId,
      title: title || '新对话',
    })
    return
  }

  const existing = chatHistory.value[index]
  if (title && (!existing.title || existing.title === '新对话')) {
    existing.title = title
  }

  chatHistory.value.splice(index, 1)
  chatHistory.value.unshift(existing)
}

const removeChatHistoryItem = (chatId: string) => {
  const index = chatHistory.value.findIndex((chat) => chat.id === chatId)
  if (index !== -1) {
    chatHistory.value.splice(index, 1)
  }
}

const scrollToBottom = async () => {
  await nextTick()
  const messageListEl = messageListRef.value
  if (messageListEl) {
    messageListEl.scrollTop = messageListEl.scrollHeight
  }
}

const stopGeneration = async () => {
  if (currentTaskId.value) {
    try {
      await stopChatMessage(currentTaskId.value)
    } catch (error) {
      if (import.meta.env.DEV) {
        console.error('停止消息生成失败:', error)
      }
    }
  }
  if (streamingAbortController) {
    streamingAbortController.abort()
    streamingAbortController = null
  }
  isLoading.value = false
  currentTaskId.value = undefined
}

const sendMessage = async () => {
  if (!inputMessage.value.trim() || isLoading.value) {
    return
  }

  const userMessage: Message = {
    role: 'user',
    content: inputMessage.value,
    timestamp: formatTime(),
  }

  messages.value.push(userMessage)
  const currentInput = inputMessage.value
  const optimisticTitle = buildConversationTitle(currentInput)
  const existingConversationId = currentConversationId.value
  let tempConversationId: string | null = null

  if (existingConversationId) {
    upsertChatHistoryToTop(existingConversationId)
  } else {
    tempConversationId = `temp-${Date.now()}`
    upsertChatHistoryToTop(tempConversationId, optimisticTitle)
  }

  inputMessage.value = ''

  isLoading.value = true
  streamingAbortController = new AbortController()

  await scrollToBottom()

  // 创建助手消息占位
  const assistantMessage: Message = {
    role: 'assistant',
    content: '',
    timestamp: formatTime(),
  }
  messages.value.push(assistantMessage)
  // Retrieve the reactive proxy that Vue wraps around the pushed object.
  // Direct assignment to the raw `assistantMessage` local variable bypasses
  // Vue's Proxy set-trap entirely, so the DOM never updates reactively.
  // All content mutations must go through this proxy reference instead.
  const reactiveAssistantMessage = messages.value[messages.value.length - 1]

  let renderedContent = ''
  let targetContent = ''
  let streamRenderTimer: number | undefined

  const stopStreamRenderer = () => {
    if (streamRenderTimer !== undefined) {
      window.clearInterval(streamRenderTimer)
      streamRenderTimer = undefined
    }
  }

  const flushRenderImmediately = () => {
    stopStreamRenderer()
    renderedContent = targetContent
    reactiveAssistantMessage.content = renderedContent
  }

  const startStreamRenderer = () => {
    if (streamRenderTimer !== undefined) {
      return
    }

    streamRenderTimer = window.setInterval(() => {
      if (renderedContent === targetContent) {
        stopStreamRenderer()
        return
      }

      const remaining = targetContent.length - renderedContent.length
      const step = Math.max(1, Math.min(8, Math.ceil(remaining / 6)))
      const nextLength = Math.min(targetContent.length, renderedContent.length + step)
      renderedContent = targetContent.slice(0, nextLength)
      reactiveAssistantMessage.content = renderedContent
      scrollToBottom()
    }, 16)
  }

  try {
    const normalizedUser = String(chatSettings.value.user ?? '').trim()

    // 调用 API
    const result = await sendChatMessage(
      currentInput,
      currentConversationId.value,
      {
        user: normalizedUser,
        search: chatSettings.value.search,
      },
      {
        onMessage: (content: string) => {
          targetContent = content
          startStreamRenderer()
        },
        onEnd: (data) => {
          // If the animation timer is not running, flush immediately.
          // If it is running, let it animate to completion naturally — do not
          // cancel it here, otherwise all buffered SSE events (which arrive in a
          // single reader.read() on loopback) would be rendered at once.
          if (streamRenderTimer === undefined) {
            flushRenderImmediately()
          }
          const conversationId =
            typeof (data as { conversation_id?: unknown }).conversation_id === 'string'
              ? (data as { conversation_id: string }).conversation_id
              : undefined
          if (conversationId) {
            currentConversationId.value = conversationId
          }
          isLoading.value = false
          currentTaskId.value = undefined
        },
        onError: (error) => {
          stopStreamRenderer()
          reactiveAssistantMessage.content = `错误: ${error.message}`
          isLoading.value = false
          currentTaskId.value = undefined
          if (import.meta.env.DEV) {
            console.error('发送消息失败:', error)
          }
        },
      }
    )

    // 保存 task_id 和 conversation_id
    currentTaskId.value = result.taskId
    if (result.conversationId) {
      currentConversationId.value = result.conversationId
    }

    const resolvedConversationId = result.conversationId || currentConversationId.value
    if (resolvedConversationId) {
      if (tempConversationId) {
        removeChatHistoryItem(tempConversationId)
      }
      upsertChatHistoryToTop(resolvedConversationId, optimisticTitle)
    }
  } catch (error: unknown) {
    if (tempConversationId) {
      removeChatHistoryItem(tempConversationId)
      if (currentConversationId.value === tempConversationId) {
        currentConversationId.value = undefined
      }
    }
    stopStreamRenderer()
    assistantMessage.content = `错误: ${getErrorMessage(error, '发送消息失败')}`
    isLoading.value = false
    currentTaskId.value = undefined
    if (import.meta.env.DEV) {
      console.error('发送消息失败:', error)
    }
  }
}

const createNewChat = () => {
  // 清空当前消息和会话 ID
  messages.value = []
  currentConversationId.value = undefined
  currentTaskId.value = undefined

  // 添加欢迎消息
  const welcomeMessage: Message = {
    role: 'assistant',
    content: '您好！我是 AI 助手，有什么可以帮助您的吗？',
    timestamp: formatTime(),
  }
  messages.value.push(welcomeMessage)
}

const loadChat = async (chatId: string) => {
  try {
    const normalizedUser = String(chatSettings.value.user ?? '').trim() || 'user'
    // 加载会话消息
    const response = await getMessages(normalizedUser, chatId)
    
    // 清空当前消息
    messages.value = []
    
    // 转换并加载消息
    if (response.data && response.data.length > 0) {
      messages.value = response.data.flatMap((msg: BackendMessageRecord) => {
        const timestamp = msg.created_at
          ? new Date(msg.created_at * 1000).toLocaleTimeString('zh-CN', {
              hour: '2-digit',
              minute: '2-digit',
            })
          : undefined

        const normalizedRole = msg.role === 'user' || msg.role === 'assistant' ? msg.role : undefined
        if (normalizedRole) {
          const roleContent = msg.content || (normalizedRole === 'assistant' ? msg.answer : msg.query) || ''
          return roleContent
            ? [
                {
                  role: normalizedRole,
                  content: roleContent,
                  timestamp,
                },
              ]
            : []
        }

        const mappedMessages: Message[] = []

        if (msg.query) {
          mappedMessages.push({
            role: 'user',
            content: msg.query,
            timestamp,
          })
        }

        if (msg.answer) {
          mappedMessages.push({
            role: 'assistant',
            content: msg.answer,
            timestamp,
          })
        }

        if (mappedMessages.length === 0 && msg.content) {
          mappedMessages.push({
            role: 'assistant',
            content: msg.content,
            timestamp,
          })
        }

        return mappedMessages
      })
    }
    
    // 设置当前会话 ID
    currentConversationId.value = chatId
    currentTaskId.value = undefined
    
    await scrollToBottom()
  } catch (error: unknown) {
    if (import.meta.env.DEV) {
      console.error('加载会话失败:', error)
    }
    // 显示错误提示（可以后续添加 Toast 提示）
  }
}

const toggleHistory = () => {
  historyCollapsed.value = !historyCollapsed.value
}

const renameChat = (chatId: string) => {
  const chat = chatHistory.value.find((c) => c.id === chatId)
  if (chat) {
    editingChatId.value = chatId
    editingChatTitle.value = chat.title
  }
}

const saveRename = (chatId: string, newTitle: string) => {
  const chat = chatHistory.value.find((c) => c.id === chatId)
  if (chat) {
    chat.title = newTitle
  }
  editingChatId.value = null
  editingChatTitle.value = ''
}

const cancelRename = () => {
  editingChatId.value = null
  editingChatTitle.value = ''
}

const handleRenameError = (_chatId: string, errorMessage: string) => {
  if (import.meta.env.DEV) {
    console.error('重命名失败:', errorMessage)
  }
}

const archiveChat = async (chatId: string) => {
  const normalizedUser = String(chatSettings.value.user ?? '').trim() || 'user'

  try {
    await archiveConversation({
      userId: normalizedUser,
      conversationId: chatId,
      limit: 20,
    })
    showSuccess('归档已完成')
  } catch (error: unknown) {
    showError(getErrorMessage(error, '归档失败'))
    if (import.meta.env.DEV) {
      console.error('归档失败:', error)
    }
  }
}

const deleteChat = (chatId: string) => {
  // TODO: 这里后续接入真实删除逻辑
  chatToDelete.value = chatId
  showDeleteDialog.value = true
}

const openSummaryDialog = () => {
  showSummaryDialog.value = true
}

const confirmDelete = async () => {
  if (chatToDelete.value) {
    const chatId = chatToDelete.value
    const deleted = await historyMessageListRef.value?.deleteConversation(chatId)

    if (deleted) {
      const index = chatHistory.value.findIndex((c) => c.id === chatId)
      if (index !== -1) {
        chatHistory.value.splice(index, 1)
      }

      if (currentConversationId.value === chatId) {
        currentConversationId.value = undefined
        currentTaskId.value = undefined
        messages.value = []
      }
    }

    chatToDelete.value = null
    showDeleteDialog.value = false
  }
}

const handleDocumentClick = () => {
  showSearchDropdown.value = false
}

onMounted(async () => {
  // 加载缓存设置
  loadCachedSettings()

  // 初始化欢迎消息
  const welcomeMessage: Message = {
    role: 'assistant',
    content: '您好！我是 AI 助手，有什么可以帮助您的吗？',
    timestamp: formatTime(),
  }
  messages.value.push(welcomeMessage)

  // 加载会话历史
  try {
    const normalizedUser = String(chatSettings.value.user ?? '').trim() || 'user'
    const response = await getConversations(normalizedUser)
    if (response.data && response.data.length > 0) {
      chatHistory.value = response.data.map((conv: Conversation) => ({
        id: conv.id,
        title: conv.name || '新对话',
      }))
    }
  } catch (error: unknown) {
    if (import.meta.env.DEV) {
      console.error('加载会话列表失败:', error)
    }
  }

  // 点击其他区域关闭菜单
  document.addEventListener('click', handleDocumentClick)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick)
  clearKnowledgeTaskPolling()
})
</script>

<style lang="scss" scoped>
.chat-page {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.chat-body {
  display: flex;
  flex: 1;
  min-height: 0;
  position: relative;
}

.chat-history-panel--collapsed {
  display: none;
}

.chat-main {
  display: flex;
  flex-direction: column;
  height: 100%;
  z-index: 1;
  overflow: hidden;
  flex: 1;
}

.chat-history-toggle {
  align-self: stretch;
  width: 20px;
  border: none;
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #5f6368;
}

.chat-history-toggle svg {
  transition: transform 0.2s ease;
}

.chat-history-toggle--collapsed svg {
  transform: rotate(180deg);
}

.chat-input-container {
  padding: 24px 32px;
  border-top: none;
  background: transparent;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.chat-input-wrapper {
  position: relative;
  margin-bottom: 8px;
  width: min(1020px, 90%);
  min-width: 560px;
  max-width: 1120px;
}

.chat-input {
  width: 100%;

  :deep(.input) {
    border: 1px solid transparent;
    background:
      linear-gradient(#ffffff, #ffffff) padding-box,
      linear-gradient(135deg, rgba(66, 133, 244, 0.6), rgba(139, 92, 246, 0.55), rgba(56, 189, 248, 0.55)) border-box;
    box-shadow: 0 0 10px rgba(66, 133, 244, 0.12);
    padding: 12px 54px 60px 16px;
    min-height: 90px;
  }

  :deep(.input:focus) {
    border: 1px solid transparent;
    box-shadow: 0 0 12px rgba(99, 102, 241, 0.18);
  }
}

.chat-input-overlay {
  position: absolute;
  bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-input-overlay--left {
  left: 12px;
}

.chat-input-overlay--right {
  right: 10px;
}

.chat-send-btn {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 50%;
  background: #4285f4;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  flex-shrink: 0;

  &:hover:not(:disabled) {
    background: #1976d2;
  }

  &:disabled {
    background: #dadce0;
    cursor: not-allowed;
    opacity: 0.5;
  }

  &--stop {
    background: #ea4335;

    &:hover {
      background: #d33426;
    }
  }
}

.chat-input-hint {
  font-size: 12px;
  color: #9aa0a6;
  text-align: center;
  margin: 0;
}

.message-list-container {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
}

.loading-indicator {
  display: flex;
  justify-content: flex-start;
  padding: 16px;
}

.loading-dots {
  display: flex;
  gap: 4px;

  span {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #4285f4;
    animation: bounce 1.4s infinite ease-in-out both;

    &:nth-child(1) {
      animation-delay: -0.32s;
    }

    &:nth-child(2) {
      animation-delay: -0.16s;
    }
  }
}

@keyframes bounce {
  0%,
  80%,
  100% {
    transform: scale(0);
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}

.search-mode-dropdown {
  flex-shrink: 0;
}

.search-mode-btn {
  height: 30px;
  padding: 0 10px;
  border: 1px solid #dadce0;
  border-radius: 15px;
  background: rgba(255, 255, 255, 0.92);
  color: #202124;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  transition: all 0.2s ease;

  &:hover {
    background: #f1f3f4;
    border-color: #bdc1c6;
    color: #202124;
  }
}

.search-mode-label {
  line-height: 1;
}

.knowledge-upload-btn {
  height: 30px;
  padding: 0 12px;
  border: 1px solid #dadce0;
  border-radius: 15px;
  background: rgba(255, 255, 255, 0.92);
  color: #202124;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
  transition: all 0.2s ease;

  &:hover:not(:disabled) {
    background: #f1f3f4;
    border-color: #bdc1c6;
    color: #202124;
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
}

.knowledge-upload-input {
  position: absolute;
  width: 0;
  height: 0;
  opacity: 0;
  pointer-events: none;
}

.search-mode-menu {
  position: fixed;
  background: #ffffff;
  border: 1px solid #e8eaed;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
  padding: 4px;
  min-width: 110px;
  z-index: 9999;
}

.search-mode-item {
  width: 100%;
  padding: 8px 12px;
  border: none;
  background: transparent;
  text-align: left;
  font-size: 13px;
  color: #202124;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s ease;
  display: block;
  white-space: nowrap;

  &:hover {
    background: #f1f3f4;
  }

  &--active {
    color: #1a73e8;
    font-weight: 600;

    &::before {
      content: '✓ ';
    }
  }
}

</style>

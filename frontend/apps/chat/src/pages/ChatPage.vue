<template>
  <div class="chat-page">
    <div class="chat-header">
      <h1 class="chat-header__title">AI</h1>
      <p class="chat-header__subtitle">与 AI 助手对话</p>
    </div>

    <div class="chat-body">
      <aside
        class="chat-history-panel"
        :class="{ 'chat-history-panel--collapsed': historyCollapsed }"
        aria-label="聊天历史"
      >
        <div class="chat-history-panel__actions">
          <button class="chat-history-panel__action" type="button" @click="createNewChat">
            <span class="chat-history-panel__icon" aria-hidden="true">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                <path
                  d="M12 5v14M5 12h14"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                />
              </svg>
            </span>
            <span class="chat-history-panel__label">新聊天</span>
          </button>
        </div>

        <div class="chat-history-panel__list">
          <div
            v-for="(chat, index) in chatHistory"
            :key="index"
            class="chat-history-item"
          >
            <div class="chat-history-item__content" @click="loadChat(chat.id)">
              <input
                v-if="editingChatId === chat.id"
                v-model="editingChatTitle"
                class="chat-history-item__title-input"
                type="text"
                @blur="saveRename(chat.id)"
                @keydown.enter="saveRename(chat.id)"
                @keydown.esc="cancelRename"
                @click.stop
              />
              <div v-else class="chat-history-item__title">{{ chat.title }}</div>
            </div>
            <div class="chat-history-item__actions">
              <button
                :ref="(el) => setChatMenuBtn(chat.id, el)"
                class="chat-history-item__menu-btn"
                type="button"
                @click.stop="toggleChatMenu(chat.id)"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                  <circle cx="12" cy="5" r="2" fill="currentColor" />
                  <circle cx="12" cy="12" r="2" fill="currentColor" />
                  <circle cx="12" cy="19" r="2" fill="currentColor" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </aside>

      <Teleport to="body">
        <div
          v-if="activeChatMenu"
          class="chat-history-item__menu"
          :style="menuPosition"
          @click.stop
        >
          <button
            class="chat-history-item__menu-item"
            type="button"
            @click="renameChat(activeChatMenu)"
          >
            重命名
          </button>
          <button
            class="chat-history-item__menu-item"
            type="button"
            @click="archiveChat(activeChatMenu)"
          >
            归档
          </button>
          <button
            class="chat-history-item__menu-item chat-history-item__menu-item--danger"
            type="button"
            @click="deleteChat(activeChatMenu)"
          >
            删除
          </button>
        </div>
      </Teleport>

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
          <div v-if="selectedFiles.length > 0" class="file-preview-list">
            <div
              v-for="(file, index) in selectedFiles"
              :key="index"
              class="file-preview-item"
            >
              <div class="file-preview-thumb">
                <img
                  v-if="isImage(file.type)"
                  :src="file.data"
                  :alt="file.name"
                  class="file-preview-img"
                />
                <div
                  v-else
                  class="file-preview-icon-bg"
                  :style="{ background: getFileIconColor(file.type) }"
                >
                  <span class="file-preview-ext">{{ getFileExt(file.name) }}</span>
                </div>
              </div>
              <span class="file-preview-name">{{ file.name }}</span>
              <button class="file-preview-remove" type="button" @click="removeFile(index)">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M18 6L6 18M6 6l12 12"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                  />
                </svg>
              </button>
            </div>
          </div>

          <div class="chat-input-wrapper">
            <input
              ref="fileInputRef"
              type="file"
              multiple
              style="display: none"
              @change="handleFileSelect"
            />
            <button class="chat-upload-btn" type="button" title="上传文件" @click="fileInputRef?.click()">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                <path
                  d="M12 5v14M5 12h14"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                />
              </svg>
            </button>
            <Input
              v-model="inputMessage"
              class="chat-input"
              placeholder="输入消息..."
              multiline
              :rows="1"
              @enter="sendMessage"
            />
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

    <ChatSettingsDialog
      v-model="showSettingsDialog"
      :initial-settings="chatSettings"
      @confirm="handleSettingsConfirm"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'
import { MessageList, MessageItem, ConfirmDialog, Input, ChatSettingsDialog } from '@yamato/components'
import type { ChatSettings } from '@yamato/components'
import { sendChatMessage, getConversations, getMessages, renameConversation as apiRenameConversation, stopChatMessage } from '../services/chat'
import type { Conversation, ChatFile } from '../types/chat'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp?: string
}

interface ChatHistoryItem {
  id: string
  title: string
}

const inputMessage = ref('')
const messages = ref<Message[]>([])
const isLoading = ref(false)
const messageListRef = ref<HTMLElement | null>(null)
const historyCollapsed = ref(false)
const activeChatMenu = ref<string | null>(null)
const menuPosition = ref({ top: '0px', left: '0px' })
const chatMenuBtns = ref<Record<string, HTMLElement>>({})
const showDeleteDialog = ref(false)
const chatToDelete = ref<string | null>(null)
const editingChatId = ref<string | null>(null)
const editingChatTitle = ref('')
const chatHistory = ref<ChatHistoryItem[]>([
  {
    id: '1',
    title: '新对话',
  },
])
const currentConversationId = ref<string | undefined>(undefined)
const currentTaskId = ref<string | undefined>(undefined)

const SETTINGS_STORAGE_KEY = 'yamato_chat_settings'
const showSettingsDialog = ref(false)
const chatSettings = ref<ChatSettings>({ userId: '', search: 'online' })
const selectedFiles = ref<ChatFile[]>([])
const fileInputRef = ref<HTMLInputElement | null>(null)

let streamingAbortController: AbortController | null = null

const setChatMenuBtn = (chatId: string, el: any) => {
  if (el) {
    chatMenuBtns.value[chatId] = el as HTMLElement
  }
}

const loadCachedSettings = () => {
  try {
    const cached = localStorage.getItem(SETTINGS_STORAGE_KEY)
    if (cached) {
      chatSettings.value = JSON.parse(cached) as ChatSettings
    }
  } catch {
    // ignore
  }
}

const handleSettingsConfirm = (settings: ChatSettings) => {
  chatSettings.value = settings
  try {
    localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings))
  } catch {
    // ignore
  }
}

const isImage = (type: string) => type.startsWith('image/')

const getFileExt = (name: string) => {
  const ext = name.split('.').pop()?.toUpperCase() ?? 'FILE'
  return ext.length > 4 ? ext.substring(0, 4) : ext
}

const getFileIconColor = (type: string) => {
  if (type.includes('pdf')) return '#FF4444'
  if (type.includes('word') || type.includes('document')) return '#2B7CD3'
  if (type.includes('excel') || type.includes('spreadsheet') || type.includes('sheet')) return '#1D6F42'
  if (type.includes('text') || type.includes('plain')) return '#888888'
  return '#5F6368'
}

const fileToBase64 = (file: File): Promise<string> => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

const handleFileSelect = async (event: Event) => {
  const input = event.target as HTMLInputElement
  if (!input.files) return
  for (const file of Array.from(input.files)) {
    const data = await fileToBase64(file)
    selectedFiles.value.push({
      name: file.name,
      type: file.type,
      size: file.size,
      data,
    })
  }
  input.value = ''
}

const removeFile = (index: number) => {
  selectedFiles.value.splice(index, 1)
}

const formatTime = (): string => {
  const now = new Date()
  return now.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })
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
  inputMessage.value = ''

  const filesToSend = [...selectedFiles.value]
  selectedFiles.value = []

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

  try {
    // 调用 API
    const result = await sendChatMessage(
      currentInput,
      currentConversationId.value,
      {
        userId: chatSettings.value.userId,
        search: chatSettings.value.search,
        files: filesToSend,
      },
      {
        onMessage: (content: string) => {
          // 流式接收消息内容
          assistantMessage.content = content
          scrollToBottom()
        },
        onEnd: (data) => {
          // 消息接收完成
          if ('conversation_id' in data) {
            currentConversationId.value = data.conversation_id
          }
          isLoading.value = false
          currentTaskId.value = undefined
        },
        onError: (error) => {
          // 错误处理
          assistantMessage.content = `错误: ${error.message}`
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
  } catch (error: any) {
    assistantMessage.content = `错误: ${error.message || '发送消息失败'}`
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
  selectedFiles.value = []

  // 添加欢迎消息
  const welcomeMessage: Message = {
    role: 'assistant',
    content: '您好！我是 AI 助手，有什么可以帮助您的吗？',
    timestamp: formatTime(),
  }
  messages.value.push(welcomeMessage)

  // 显示设置弹窗
  showSettingsDialog.value = true
}

const loadChat = async (chatId: string) => {
  activeChatMenu.value = null
  
  try {
    // 加载会话消息
    const response = await getMessages(chatId)
    
    // 清空当前消息
    messages.value = []
    
    // 转换并加载消息
    if (response.data && response.data.length > 0) {
      messages.value = response.data.map((msg: any) => ({
        role: msg.role || (msg.answer ? 'assistant' : 'user'),
        content: msg.answer || msg.query || msg.content || '',
        timestamp: msg.created_at ? new Date(msg.created_at * 1000).toLocaleTimeString('zh-CN', {
          hour: '2-digit',
          minute: '2-digit',
        }) : undefined,
      }))
    }
    
    // 设置当前会话 ID
    currentConversationId.value = chatId
    currentTaskId.value = undefined
    
    await scrollToBottom()
  } catch (error: any) {
    if (import.meta.env.DEV) {
      console.error('加载会话失败:', error)
    }
    // 显示错误提示（可以后续添加 Toast 提示）
  }
}

const toggleHistory = () => {
  historyCollapsed.value = !historyCollapsed.value
}

const toggleChatMenu = (chatId: string) => {
  if (activeChatMenu.value === chatId) {
    activeChatMenu.value = null
    return
  }

  const btn = chatMenuBtns.value[chatId]
  if (btn) {
    const rect = btn.getBoundingClientRect()
    menuPosition.value = {
      top: `${rect.top}px`,
      left: `${rect.right + 4}px`,
    }
  }
  
  activeChatMenu.value = chatId
}

const renameChat = (chatId: string) => {
  const chat = chatHistory.value.find((c) => c.id === chatId)
  if (chat) {
    editingChatId.value = chatId
    editingChatTitle.value = chat.title
    activeChatMenu.value = null
    
    nextTick(() => {
      const input = document.querySelector('.chat-history-item__title-input') as HTMLInputElement
      if (input) {
        input.focus()
        input.select()
      }
    })
  }
}

const saveRename = async (chatId: string) => {
  const chat = chatHistory.value.find((c) => c.id === chatId)
  if (chat && editingChatTitle.value.trim()) {
    const newTitle = editingChatTitle.value.trim()
    
    try {
      // 调用 API 重命名会话
      await apiRenameConversation(chatId, newTitle)
      chat.title = newTitle
    } catch (error: any) {
      if (import.meta.env.DEV) {
        console.error('重命名失败:', error)
      }
      // 可以添加错误提示
    }
  }
  editingChatId.value = null
  editingChatTitle.value = ''
}

const cancelRename = () => {
  editingChatId.value = null
  editingChatTitle.value = ''
}

const archiveChat = (chatId: string) => {
  // TODO: 这里后续接入真实归档逻辑
  if (import.meta.env.DEV) {
    // eslint-disable-next-line no-console
    console.log('Archive chat:', chatId)
  }
  activeChatMenu.value = null
}

const deleteChat = (chatId: string) => {
  // TODO: 这里后续接入真实删除逻辑
  chatToDelete.value = chatId
  showDeleteDialog.value = true
  activeChatMenu.value = null
}

const confirmDelete = () => {
  if (chatToDelete.value) {
    const index = chatHistory.value.findIndex((c) => c.id === chatToDelete.value)
    if (index !== -1) {
      chatHistory.value.splice(index, 1)
    }
    chatToDelete.value = null
  }
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

  // 显示设置弹窗
  showSettingsDialog.value = true

  // 加载会话历史
  try {
    const response = await getConversations()
    if (response.data && response.data.length > 0) {
      chatHistory.value = response.data.map((conv: Conversation) => ({
        id: conv.id,
        title: conv.name || '新对话',
      }))
    }
  } catch (error: any) {
    if (import.meta.env.DEV) {
      console.error('加载会话列表失败:', error)
    }
  }

  // 点击其他区域关闭菜单
  document.addEventListener('click', () => {
    activeChatMenu.value = null
  })
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

.chat-history-panel {
  width: 160px; 
  background: #ffffff;
  border-right: 1px solid #e8eaed;
  padding: 8px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.chat-history-panel--collapsed {
  display: none;
}

.chat-history-panel__actions {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 8px;
  padding-left: 4px; /* 缩进减小，让内容更靠左 */
  padding-right: 4px;
}

.chat-history-panel__action {
  height: 40px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: #202124;
  cursor: pointer;
  text-align: left;
  padding: 0 12px;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
  transition: background 0.2s ease;

  &:hover {
    background: #f1f3f4;
  }
}

.chat-history-panel__icon {
  width: 14px;
  height: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #5f6368;
  flex: 0 0 auto;
}

.chat-history-panel__label {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-history-panel__list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding-left: 4px;
  padding-right: 4px;
  min-height: 0;
}

.chat-history-item {
  padding: 8px;
  border-radius: 10px;
  margin-bottom: 4px;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;

  &:hover {
    background: #f1f3f4;

    .chat-history-item__menu-btn {
      opacity: 1;
    }
  }
}

.chat-history-item__title-input {
  width: 100%;
  max-width: 100%;
  font-size: 13px;
  font-weight: 600;
  color: #202124;
  border: 1px solid #4285f4;
  border-radius: 4px;
  padding: 2px 4px;
  outline: none;
  background: #ffffff;
  box-sizing: border-box;
}

.chat-history-item__content {
  flex: 1;
  min-width: 0;
  cursor: pointer;
}

.chat-history-item__title {
  font-size: 13px;
  font-weight: 600;
  color: #202124;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.chat-history-item__actions {
  position: static;
  flex-shrink: 0;
}

.chat-history-item__menu-btn {
  width: 24px;
  height: 24px;
  border: none;
  background: transparent;
  border-radius: 4px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #5f6368;
  opacity: 0;
  transition: opacity 0.2s ease, background 0.2s ease;
  position: relative;

  &:hover {
    background: #e8eaed;
  }
}

.chat-history-item__menu {
  position: fixed;
  background: #ffffff;
  border: 1px solid #e8eaed;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  padding: 4px;
  min-width: 120px;
  z-index: 9999;
  white-space: nowrap;
}

.chat-history-item__menu-item {
  width: 100%;
  padding: 8px 12px;
  border: none;
  background: transparent;
  text-align: left;
  font-size: 13px;
  color: #202124;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.2s ease;
  display: block;

  &:hover {
    background: #f1f3f4;
  }

  &--danger {
    color: #d93025;

    &:hover {
      background: #fce8e6;
    }
  }
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

.chat-header {
  padding: 14px 32px;
  border-bottom: none;
  background: #ffffff;

  &__title {
    font-size: 24px;
    font-weight: 500;
    color: #1976d2;
    margin: 0 0 4px 0;
    line-height: 1.2;
  }

  &__subtitle {
    font-size: 14px;
    color: #5f6368;
    margin: 0;
    line-height: 1.2;
  }
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
  width: 70%;
  min-width: 480px;
  max-width: 960px;
  display: flex;
  align-items: flex-end;
  gap: 8px;
}

.chat-upload-btn {
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: #5f6368;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  flex-shrink: 0;
  margin-bottom: 4px;

  &:hover {
    background: #f1f3f4;
  }
}

.chat-input {
  flex: 1;
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
  margin-bottom: 4px;

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
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}

.file-preview-list {
  width: 70%;
  min-width: 480px;
  max-width: 960px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.file-preview-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px 4px 4px;
  background: #f1f3f4;
  border: 1px solid #e8eaed;
  border-radius: 8px;
  max-width: 220px;
}

.file-preview-thumb {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: 4px;
  overflow: hidden;
}

.file-preview-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.file-preview-icon-bg {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
}

.file-preview-ext {
  font-size: 9px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 0.5px;
}

.file-preview-name {
  font-size: 12px;
  color: #202124;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 120px;
  flex: 1;
}

.file-preview-remove {
  width: 18px;
  height: 18px;
  border: none;
  background: transparent;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9aa0a6;
  border-radius: 50%;
  flex-shrink: 0;
  padding: 0;

  &:hover {
    background: #e8eaed;
    color: #5f6368;
  }
}

</style>

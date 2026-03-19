<!--
  渲染聊天界面中的单条消息（用户 / AI）

  功能：
  1. 根据 role 区分用户消息和 AI 消息
  2. 用户消息：纯文本展示
  3. AI 消息：支持 Markdown 渲染（代码块、列表、表格等）
  4. AI 流式输出：支持从 &lt;think&gt;...&lt;/think&gt; 中分离“思考过程”和“最终答案”
  5. 流式阶段：当 &lt;think&gt; 尚未闭合时，实时展示思考内容；闭合后自动切换到答案流
  6. 思考区可折叠，并在答案开始后自动收起（仍可手动展开）
  7. 显示头像（用户 / AI）
  8. 可选显示消息时间

  使用场景：
  聊天页面 MessageList 中循环渲染消息列表
-->
 
<template>
  <div :class="['message-item', `message-item--${role}`]">
    <div class="message-item__avatar">
      <div v-if="role === 'user'" class="avatar avatar--user">U</div>
      <img
        v-else-if="assistantAvatarUrl"
        :src="assistantAvatarUrl"
        class="avatar avatar--assistant-img"
        alt="AI"
      />
      <div v-else class="avatar avatar--assistant">AI</div>
    </div>
    <div class="message-item__content">
      <template v-if="role === 'assistant'">
        <details
          v-if="hasThought"
          class="message-item__thought"
          :open="thoughtExpanded"
        >
          <summary class="message-item__thought-summary" @click.prevent="toggleThought">
            💭 思考过程
          </summary>
          <div
            v-if="isStreaming"
            :class="[
              'message-item__text',
              'message-item__stream-text',
              { 'message-item__thought-content--clamped': clampThoughtDuringAnswer },
            ]"
          >{{ parsedAssistantContent.thought }}</div>
          <div
            v-else
            :class="[
              'message-item__text',
              'message-item__markdown',
              { 'message-item__thought-content--clamped': clampThoughtDuringAnswer },
            ]"
            v-html="renderedThoughtMarkdown"
          ></div>
        </details>
        <div v-if="isStreaming" class="message-item__text message-item__stream-text">{{ parsedAssistantContent.answer }}</div>
        <div v-else class="message-item__text message-item__markdown" v-html="renderedAnswerMarkdown"></div>
      </template>
      <div v-else class="message-item__text">{{ content }}</div>
      <div v-if="timestamp" class="message-item__time">{{ timestamp }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'

interface Props {
  role: 'user' | 'assistant'
  content: string
  timestamp?: string
  isStreaming?: boolean
  assistantAvatarUrl?: string
}

const props = defineProps<Props>()
const isStreaming = computed(() => Boolean(props.isStreaming))

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const wrapTableScrollContainer = (html: string): string => {
  return html
    .replace(/<table>/g, '<div class="message-item__table-scroll"><table>')
    .replace(/<\/table>/g, '</table></div>')
}

const splitAssistantContent = (content: string): { thought: string; answer: string } => {
  const text = content || ''
  const thinkStartTag = '<think>'
  const thinkEndTag = '</think>'
  const thinkStartIndex = text.indexOf(thinkStartTag)
  const thinkEndIndex = text.indexOf(thinkEndTag)

  const sanitizeThought = (value: string): string =>
    value.replace(/<\/?think>/g, '').trim()

  const sanitizeAnswer = (value: string): string =>
    value.replace(/<\/?think>/g, '').replace(/^\s+/, '')

  if (thinkStartIndex !== -1 && thinkEndIndex === -1) {
    return {
      thought: sanitizeThought(text.slice(thinkStartIndex + thinkStartTag.length)),
      answer: '',
    }
  }

  if (thinkEndIndex === -1) {
    return {
      thought: '',
      answer: sanitizeAnswer(text),
    }
  }

  const rawThought = thinkStartIndex !== -1
    ? text.slice(thinkStartIndex + thinkStartTag.length, thinkEndIndex)
    : text.slice(0, thinkEndIndex)
  const rawAnswer = text.slice(thinkEndIndex + thinkEndTag.length)

  return {
    thought: sanitizeThought(rawThought),
    answer: sanitizeAnswer(rawAnswer),
  }
}

const parsedAssistantContent = computed(() => splitAssistantContent(props.content || ''))
const hasThought = computed(() => parsedAssistantContent.value.thought.length > 0)
const hasAnswer = computed(() => parsedAssistantContent.value.answer.trim().length > 0)
const clampThoughtDuringAnswer = computed(() => Boolean(props.isStreaming && hasAnswer.value))
const renderedThoughtMarkdown = computed(() =>
  wrapTableScrollContainer(md.render(parsedAssistantContent.value.thought || ''))
)
const renderedAnswerMarkdown = computed(() =>
  wrapTableScrollContainer(md.render(parsedAssistantContent.value.answer || ''))
)

const thoughtExpanded = ref(true)
const hasAutoCollapsedForCurrentMessage = ref(false)

watch(
  () => props.content,
  () => {
    const nextHasThought = hasThought.value
    const nextHasAnswer = hasAnswer.value

    if (!nextHasThought) {
      thoughtExpanded.value = true
      hasAutoCollapsedForCurrentMessage.value = false
      return
    }

    if (nextHasThought && !nextHasAnswer) {
      thoughtExpanded.value = true
      hasAutoCollapsedForCurrentMessage.value = false
      return
    }

    if (nextHasThought && nextHasAnswer && !hasAutoCollapsedForCurrentMessage.value) {
      thoughtExpanded.value = false
      hasAutoCollapsedForCurrentMessage.value = true
    }
  },
  { immediate: true }
)

const toggleThought = () => {
  thoughtExpanded.value = !thoughtExpanded.value
}
</script>

<style lang="scss" scoped>
.message-item {
  display: flex;
  gap: 16px;
  padding: 16px;
  border-radius: 8px;
  transition: none;

  &--user {
    flex-direction: row-reverse;

    .message-item__content {
      align-items: flex-end;
    }

    .message-item__text {
      background: transparent;
      color: #202124;
    }
  }

  &--assistant {
    .message-item__content {
      max-width: 80%;
    }

    .message-item__text {
      background: transparent;
      color: #202124;
      border: none;
    }
  }

  &__avatar {
    flex-shrink: 0;
  }

  &__content {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 8px;
    max-width: 70%;
  }

  &__text {
    padding: 0;
    border-radius: 0;
    line-height: 1.6;
    word-wrap: break-word;
    overflow-x: visible;
  }

  &__time {
    font-size: 12px;
    color: #9aa0a6;
    padding: 0 4px;
  }
}

.message-item__markdown {
  :deep(p) {
    margin: 0 0 12px;
  }

  :deep(p:last-child) {
    margin-bottom: 0;
  }

  :deep(ul),
  :deep(ol) {
    margin: 0 0 12px;
    padding-left: 20px;
  }

  :deep(pre) {
    margin: 0 0 12px;
    padding: 12px;
    border-radius: 8px;
    background: #f5f5f5;
    overflow-x: auto;
  }

  :deep(code) {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
      'Courier New', monospace;
  }

  :deep(table) {
    width: max-content;
    min-width: 100%;
    border-collapse: collapse;
    margin: 0 0 12px;
  }

  :deep(th),
  :deep(td) {
    border: 1px solid #e0e0e0;
    padding: 8px 10px;
    text-align: left;
    vertical-align: top;
  }

  :deep(th) {
    background: #fafafa;
    font-weight: 600;
  }

  :deep(.message-item__table-scroll) {
    width: 100%;
    overflow-x: auto;
    overflow-y: hidden;
    margin: 0 0 12px;
    scrollbar-width: thin;
    scrollbar-color: #cfd3d9 #f5f6f8;
  }

  :deep(.message-item__table-scroll::-webkit-scrollbar) {
    height: 8px;
  }

  :deep(.message-item__table-scroll::-webkit-scrollbar-track) {
    background: #f5f6f8;
    border-radius: 999px;
  }

  :deep(.message-item__table-scroll::-webkit-scrollbar-thumb) {
    background: #cfd3d9;
    border-radius: 999px;
  }

  :deep(.message-item__table-scroll::-webkit-scrollbar-thumb:hover) {
    background: #bfc5cc;
  }
}

.message-item__thought {
  border-radius: 8px;
  background: #f1f5f9;
  border-left: 4px solid #3b82f6;
  padding: 10px 12px;

  &[open] {
    padding-bottom: 12px;
  }
}

.message-item__thought-summary {
  cursor: pointer;
  color: #1e40af;
  font-size: 13px;
  font-weight: 600;
  user-select: none;
}

.message-item__thought-content--clamped {
  max-height: calc(1.6em * 5);
  overflow-y: auto;
  overflow-x: hidden;
}

.message-item__stream-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 500;
  font-size: 14px;

  &--user {
    background: #4285f4;
    color: white;
  }

  &--assistant {
    background: #34a853;
    color: white;
  }

  &--assistant-img {
    width: 40px;
    height: 40px;
    border-radius: 50%;
    object-fit: cover;
    display: block;
  }
}
</style>

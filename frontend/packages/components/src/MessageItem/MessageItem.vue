<template>
  <div :class="['message-item', `message-item--${role}`]">
    <div class="message-item__avatar">
      <div v-if="role === 'user'" class="avatar avatar--user">U</div>
      <div v-else class="avatar avatar--assistant">AI</div>
    </div>
    <div class="message-item__content">
      <div class="message-item__text">{{ content }}</div>
      <div v-if="timestamp" class="message-item__time">{{ timestamp }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
interface Props {
  role: 'user' | 'assistant'
  content: string
  timestamp?: string
}

defineProps<Props>()
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
  }

  &__time {
    font-size: 12px;
    color: #9aa0a6;
    padding: 0 4px;
  }
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
}
</style>

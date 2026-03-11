<template>
  <div class="message-list">
    <slot />
  </div>
</template>

<script setup lang="ts">
// MessageList component
</script>

<style lang="scss" scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>

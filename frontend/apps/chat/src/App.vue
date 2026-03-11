<template>
  <div id="app" class="app-shell">
    <Sidebar
      title="yamato"
      :user-name="userName"
      :user-avatar-url="userAvatarUrl"
      user-desc="在线"
      :collapsible="false"
      :width="168"
    >
      <nav class="sidebar-nav" aria-label="主导航">
        <RouterLink class="sidebar-nav__item" active-class="is-active" to="/chat">
          AI聊天
        </RouterLink>
        <RouterLink class="sidebar-nav__item" active-class="is-active" to="/files">
          文件管理
        </RouterLink>
        <RouterLink class="sidebar-nav__item" active-class="is-active" to="/policy">
          报单生成
        </RouterLink>
      </nav>
    </Sidebar>

    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { Sidebar } from '@yamato/components'
import { config } from './config'

const userName = computed(() => config.userName || '')
const userAvatarUrl = computed(() => config.userAvatarUrl || '')
</script>

<style scoped lang="scss">
.app-shell {
  width: 100%;
  height: 100vh;
  overflow: hidden;
}

.app-main {
  height: 100%;
  padding-left: 168px;
  overflow: hidden;
  background: #ffffff;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
}

.sidebar-nav__item {
  display: flex;
  align-items: center;
  height: 40px;
  padding: 0 12px;
  border-radius: 10px;
  color: #202124;
  text-decoration: none;
  font-size: 14px;
  transition: background 0.2s ease, color 0.2s ease;

  &:hover {
    background: #e8eaed;
  }

  &.is-active {
    background: #d2e3fc;
    color: #1976d2;
    font-weight: 600;
  }
}
</style>

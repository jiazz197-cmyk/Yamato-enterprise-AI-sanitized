<template>
  <div v-if="isLoginPage" class="login-shell">
    <RouterView />
  </div>
  <div v-else id="app" class="app-shell">
    <Sidebar
      title="yamato"
      logo-url="/yamato_icon.png"
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
          报单填写
        </RouterLink>
      </nav>

      <template #user-actions>
        <button class="logout-btn" type="button" @click="openLogoutDialog">
          退出
        </button>
      </template>
    </Sidebar>

    <main class="app-main">
      <RouterView />
    </main>

    <ConfirmDialog
      v-model="showLogoutDialog"
      title="退出登录"
      message="确定要退出当前账号吗？"
      type="warning"
      confirm-text="退出"
      cancel-text="取消"
      @confirm="confirmLogout"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { Sidebar, ConfirmDialog } from '@yamato/components'
import { config } from './config'
import { useIdleTimer } from './composables/useIdleTimer'

const sidebarUserId = ref('')

const readSidebarUserId = () => {
  try {
    const raw = localStorage.getItem(config.settingsStorageKey)
    if (!raw) {
      sidebarUserId.value = ''
      return
    }

    const parsed = JSON.parse(raw) as { userId?: unknown; user?: unknown }
    sidebarUserId.value = String(parsed.userId ?? parsed.user ?? '').trim()
  } catch {
    sidebarUserId.value = ''
  }
}

const userName = computed(() => sidebarUserId.value || config.userName || '')
const userAvatarUrl = computed(() => config.userAvatarUrl || '')

const route = useRoute()
const router = useRouter()

const showLogoutDialog = ref(false)

const isLoginPage = computed(() => route.name === 'login')

readSidebarUserId()

watch(
  () => route.fullPath,
  () => {
    readSidebarUserId()
  }
)

const openLogoutDialog = () => {
  showLogoutDialog.value = true
}

const confirmLogout = async () => {
  try {
    localStorage.removeItem(config.authTokenStorageKey)
  } catch {
    // ignore
  }
  await router.push('/login')
}

const IDLE_TIMEOUT_MS = 10 * 60 * 1000

const autoLogout = async () => {
  try {
    localStorage.removeItem(config.authTokenStorageKey)
  } catch {
    // ignore
  }
  await router.push('/login')
}

const { start: startIdleTimer, stop: stopIdleTimer } = useIdleTimer(IDLE_TIMEOUT_MS, () => {
  void autoLogout()
})

if (!isLoginPage.value) {
  startIdleTimer()
}

watch(isLoginPage, (onLoginPage) => {
  if (onLoginPage) {
    stopIdleTimer()
  } else {
    startIdleTimer()
  }
})
</script>

<style scoped lang="scss">
.app-shell {
  width: 100%;
  height: 100vh;
  overflow: hidden;
}

.login-shell {
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

.logout-btn {
  padding: 4px 10px;
  border-radius: 999px;
  border: none;
  background: #e8f0fe;
  color: #1a73e8;
  font-size: 12px;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.2s ease, color 0.2s ease, transform 0.1s ease;

  &:hover {
    background: #d2e3fc;
    color: #174ea6;
  }

  &:active {
    transform: translateY(1px);
  }
}
</style>

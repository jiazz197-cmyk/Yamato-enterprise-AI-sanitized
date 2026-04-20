<template>
  <div v-if="isShellFreePage" class="login-shell">
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
      :width="200"
    >
      <nav class="sidebar-nav" aria-label="主导航">
        <RouterLink class="sidebar-nav__item" active-class="is-active" to="/chat">
          AI聊天
        </RouterLink>
        <RouterLink class="sidebar-nav__item" active-class="is-active" to="/files">
          文件管理
        </RouterLink>
        <RouterLink class="sidebar-nav__item" active-class="is-active" to="/closing-form">
          报单填写
        </RouterLink>
        <RouterLink v-if="isAdminOrSuperuser" class="sidebar-nav__item" active-class="is-active" to="/collection2">
          知识库管理
        </RouterLink>
        <RouterLink v-if="isSuperuser" class="sidebar-nav__item" active-class="is-active" to="/users">
          用户管理
        </RouterLink>
      </nav>

      <div id="sidebar-extra-slot" class="sidebar-extra"></div>

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
      @confirm="doLogout"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { Sidebar, ConfirmDialog } from '@yamato/components'
import { config } from './config'
import { useIdleTimer } from './composables/useIdleTimer'
import { clearAuthTokenFromStorage } from './services/token_storage'

const sidebarUserId = ref('')
const sidebarUserName = ref('')
const userRole = ref('')

const readSidebarState = () => {
  try {
    const raw = localStorage.getItem(config.settingsStorageKey)
    if (!raw) {
      sidebarUserId.value = ''
      sidebarUserName.value = ''
      userRole.value = ''
      return
    }

    const parsed = JSON.parse(raw) as {
      userId?: unknown
      user?: unknown
      userName?: unknown
      username?: unknown
      role?: unknown
    }
    sidebarUserId.value = String(parsed.userId ?? '').trim()
    sidebarUserName.value = String(parsed.userName ?? parsed.user ?? parsed.username ?? '').trim()
    userRole.value = String(parsed.role ?? '').trim()
  } catch {
    sidebarUserId.value = ''
    sidebarUserName.value = ''
    userRole.value = ''
  }
}

const userName = computed(() => sidebarUserName.value || sidebarUserId.value || config.userName || '')
const userAvatarUrl = computed(() => config.userAvatarUrl || '')
const isSuperuser = computed(() => userRole.value === 'superuser')
const isAdminOrSuperuser = computed(() => userRole.value === 'admin' || userRole.value === 'superuser')

const route = useRoute()
const router = useRouter()

const showLogoutDialog = ref(false)

const isShellFreePage = computed(() => route.name === 'login' || route.name === 'register')

readSidebarState()

watch(
  () => route.fullPath,
  () => {
    readSidebarState()
  }
)

const openLogoutDialog = () => {
  showLogoutDialog.value = true
}

const doLogout = async () => {
  clearAuthTokenFromStorage()
  try {
    localStorage.removeItem(config.settingsStorageKey)
  } catch {
    // 忽略
  }
  await router.push('/login')
}

const IDLE_TIMEOUT_MS = 10 * 60 * 1000

const { start: startIdleTimer, stop: stopIdleTimer } = useIdleTimer(IDLE_TIMEOUT_MS, () => {
  void doLogout()
})

if (!isShellFreePage.value) {
  startIdleTimer()
}

watch(isShellFreePage, (onShellFreePage) => {
  if (onShellFreePage) {
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
  background: #f8f9fa;
}

.login-shell {
  width: 100%;
  height: 100vh;
  overflow: hidden;
}

.app-main {
  height: 100%;
  padding-left: 212px;
  overflow: hidden;
  background: #f8f9fa;
}

.sidebar-extra {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0 8px;
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

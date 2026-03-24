<template>
  <div class="login-page">
    <div class="login-card" role="form" aria-label="登录">
      <h1 class="login-card__title">登录</h1>
      <p class="login-card__subtitle">请输入账号和密码以继续使用系统</p>

      <form class="login-form" @submit.prevent="handleSubmit">
        <label class="login-form__field">
          <span class="login-form__label">用户名</span>
          <Input
            v-model="username"
            class="login-form__input"
            placeholder="请输入用户名"
            autocomplete="username"
          />
        </label>

        <label class="login-form__field">
          <span class="login-form__label">密码</span>
          <Input
            v-model="password"
            class="login-form__input"
            type="password"
            placeholder="请输入密码"
            autocomplete="current-password"
          />
        </label>

        <button
          class="login-form__submit"
          type="submit"
          :disabled="submitting || !username.trim() || !password"
        >
          {{ submitting ? '登录中...' : '登录' }}
        </button>
      </form>

      <p class="login-card__footer">
        没有账号？
        <RouterLink class="login-card__link" to="/register">去注册</RouterLink>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { Input, useToast } from '@yamato/components'
import { config } from '../config'
import { login, getMe, saveUserRole } from '../services/auth'

const router = useRouter()
const { showSuccess, showError } = useToast()

const username = ref('')
const password = ref('')
const submitting = ref(false)

const handleSubmit = async () => {
  if (submitting.value) return

  submitting.value = true
  try {
    const result = await login({
      username: username.value.trim(),
      password: password.value,
    })

    try {
      localStorage.setItem(config.authTokenStorageKey, result.access_token)
    } catch {
      // ignore storage error
    }

    try {
      const me = await getMe()
      const existing = JSON.parse(localStorage.getItem(config.settingsStorageKey) || '{}')
      const loginUserId = String(me.id || '').trim()
      const loginUser = String(me.username || me.id || '').trim()
      const loginUserName = String((me as any).name || me.username || me.id || '').trim()
      localStorage.setItem(
        config.settingsStorageKey,
        JSON.stringify({
          ...existing,
          userId: loginUser,
          userUUID: loginUserId,
          user: loginUser,
          userName: loginUserName,
          username: loginUser,
          role: me.role || '',
          search: existing.search || '联网搜索',
        })
      )
      saveUserRole(me.role || '')
    } catch {
      // ignore: user info is best-effort
    }

    showSuccess('登录成功')
    await router.push('/chat')
  } catch (error: any) {
    const message = error?.message || '登录失败，请检查账号密码'
    showError(message)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped lang="scss">
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100vh;
  background: radial-gradient(circle at top left, #e8f0fe 0, #ffffff 40%, #f1f3f4 100%);
}

.login-card {
  width: 360px;
  padding: 32px 32px 28px;
  border-radius: 16px;
  background: #ffffff;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.12);
  box-sizing: border-box;
}

.login-card__title {
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 600;
  color: #202124;
}

.login-card__subtitle {
  margin: 0 0 24px;
  font-size: 13px;
  color: #5f6368;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.login-form__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.login-form__label {
  font-size: 13px;
  color: #5f6368;
}

.login-form__input {
  width: 100%;
}

.login-card__footer {
  margin: 20px 0 0;
  font-size: 13px;
  color: #5f6368;
  text-align: center;
}

.login-card__link {
  color: #1a73e8;
  text-decoration: none;
  font-weight: 500;

  &:hover {
    text-decoration: underline;
  }
}

.login-form__submit {
  margin-top: 8px;
  width: 100%;
  height: 40px;
  border: none;
  border-radius: 999px;
  background: #1a73e8;
  color: #ffffff;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s ease, box-shadow 0.2s ease, transform 0.1s ease;

  &:hover:not(:disabled) {
    background: #185abc;
    box-shadow: 0 2px 6px rgba(26, 115, 232, 0.35);
  }

  &:active:not(:disabled) {
    transform: translateY(1px);
    box-shadow: 0 1px 3px rgba(26, 115, 232, 0.4);
  }

  &:disabled {
    background: #dadce0;
    cursor: not-allowed;
  }
}
</style>


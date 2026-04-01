<template>
  <div class="register-page">
    <div class="register-card" role="form" aria-label="注册">
      <h1 class="register-card__title">创建账号</h1>
      <p class="register-card__subtitle">填写以下信息完成注册</p>

      <form class="register-form" @submit.prevent="handleSubmit">
        <label class="register-form__field">
          <span class="register-form__label">用户名 <em class="required">*</em></span>
          <Input
            v-model="username"
            class="register-form__input"
            placeholder="请输入用户名"
            autocomplete="username"
          />
        </label>

        <label class="register-form__field">
          <span class="register-form__label">邮箱 <em class="required">*</em></span>
          <Input
            v-model="email"
            class="register-form__input"
            type="email"
            placeholder="请输入邮箱地址"
            autocomplete="email"
          />
        </label>

        <label class="register-form__field">
          <span class="register-form__label">密码 <em class="required">*</em></span>
          <Input
            v-model="password"
            class="register-form__input"
            type="password"
            placeholder="请输入密码（至少 6 位）"
            autocomplete="new-password"
          />
        </label>

        <label class="register-form__field">
          <span class="register-form__label">姓名（选填）</span>
          <Input
            v-model="name"
            class="register-form__input"
            placeholder="请输入真实姓名"
            autocomplete="name"
          />
        </label>

        <button
          class="register-form__submit"
          type="submit"
          :disabled="submitting || !canSubmit"
        >
          {{ submitting ? '注册中...' : '注册' }}
        </button>
      </form>

      <p class="register-card__footer">
        已有账号？
        <RouterLink class="register-card__link" to="/login">去登录</RouterLink>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { Input, useToast } from '@yamato/components'
import { register } from '../services/auth'

const router = useRouter()
const { showSuccess, showError } = useToast()

const username = ref('')
const email = ref('')
const password = ref('')
const name = ref('')
const submitting = ref(false)

const canSubmit = computed(
  () =>
    username.value.trim() !== '' &&
    email.value.trim() !== '' &&
    password.value.length >= 6
)

const handleSubmit = async () => {
  if (submitting.value || !canSubmit.value) return

  submitting.value = true
  try {
    await register({
      username: username.value.trim(),
      email: email.value.trim(),
      password: password.value,
      name: name.value.trim() || undefined,
    })
    showSuccess('注册成功，请登录')
    await router.push('/login')
  } catch (error: any) {
    const detail = error?.detail ?? error?.message
    showError(detail || '注册失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped lang="scss">
.register-page {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100vh;
  background: radial-gradient(circle at top left, #e8f0fe 0, #ffffff 40%, #f1f3f4 100%);
}

.register-card {
  width: 360px;
  padding: 32px 32px 28px;
  border-radius: 16px;
  background: #ffffff;
  box-shadow: 0 16px 40px rgba(0, 0, 0, 0.12);
  box-sizing: border-box;
}

.register-card__title {
  margin: 0 0 8px;
  font-size: 24px;
  font-weight: 600;
  color: #202124;
}

.register-card__subtitle {
  margin: 0 0 24px;
  font-size: 13px;
  color: #5f6368;
}

.register-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.register-form__field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.register-form__label {
  font-size: 13px;
  color: #5f6368;
}

.required {
  font-style: normal;
  color: #ea4335;
}

.register-form__input {
  width: 100%;
}

.register-form__submit {
  margin-top: 6px;
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

.register-card__footer {
  margin: 20px 0 0;
  font-size: 13px;
  color: #5f6368;
  text-align: center;
}

.register-card__link {
  color: #1a73e8;
  text-decoration: none;
  font-weight: 500;

  &:hover {
    text-decoration: underline;
  }
}
</style>

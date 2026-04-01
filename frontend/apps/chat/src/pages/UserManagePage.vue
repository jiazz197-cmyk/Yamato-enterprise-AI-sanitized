<template>
  <div class="user-manage-page">
    <div class="user-manage-header">
      <div class="user-manage-header__left">
        <h1 class="user-manage-header__title">用户管理</h1>
        <span class="user-manage-header__count">共 {{ users.length }} 位用户</span>
      </div>
      <button class="refresh-btn" :disabled="loading" @click="loadUsers">
        <span class="refresh-btn__icon" :class="{ 'is-spinning': loading }">↻</span>
        刷新
      </button>
    </div>

    <div class="user-manage-content">
      <div v-if="loading && users.length === 0" class="state-placeholder">
        加载中...
      </div>

      <div v-else-if="!loading && users.length === 0" class="state-placeholder">
        暂无用户数据
      </div>

      <table v-else class="user-table">
        <thead>
          <tr>
            <th class="user-table__th">用户名</th>
            <th class="user-table__th">姓名</th>
            <th class="user-table__th">邮箱</th>
            <th class="user-table__th">角色</th>
            <th class="user-table__th user-table__th--actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.id" class="user-table__row">
            <td class="user-table__td user-table__td--username">{{ user.username }}</td>
            <td class="user-table__td">{{ user.name || '—' }}</td>
            <td class="user-table__td user-table__td--email">{{ user.email }}</td>
            <td class="user-table__td">
              <span class="role-badge" :class="`role-badge--${user.role}`">
                {{ roleLabel(user.role) }}
              </span>
            </td>
            <td class="user-table__td user-table__td--actions">
              <template v-if="user.role !== 'superuser'">
                <button
                  class="action-btn action-btn--role"
                  :disabled="actionPending === user.id"
                  @click="toggleRole(user)"
                >
                  {{ user.role === 'admin' ? '降为普通用户' : '设为管理员' }}
                </button>
                <button
                  class="action-btn action-btn--delete"
                  :disabled="actionPending === user.id"
                  @click="openDeleteDialog(user)"
                >
                  删除
                </button>
              </template>
              <span v-else class="self-label">超级管理员</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ConfirmDialog
      v-model="showDeleteDialog"
      title="删除用户"
      :message="`确定要删除用户「${pendingDeleteUser?.username}」吗？此操作不可恢复。`"
      type="danger"
      confirm-text="删除"
      cancel-text="取消"
      @confirm="confirmDelete"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ConfirmDialog, useToast } from '@yamato/components'
import { listUsers, deleteUser, updateUserRole } from '../services/auth'
import type { UserResponse } from '../services/auth'

const { showSuccess, showError } = useToast()

const users = ref<UserResponse[]>([])
const loading = ref(false)
const actionPending = ref<string | null>(null)

const showDeleteDialog = ref(false)
const pendingDeleteUser = ref<UserResponse | null>(null)

const roleLabel = (role: string) => {
  if (role === 'superuser') return '超级管理员'
  if (role === 'admin') return '管理员'
  return '普通用户'
}

const loadUsers = async () => {
  loading.value = true
  try {
    users.value = await listUsers()
  } catch (error: any) {
    showError(error?.message || '加载用户列表失败')
  } finally {
    loading.value = false
  }
}

const toggleRole = async (user: UserResponse) => {
  const newRole = user.role === 'admin' ? 'user' : 'admin'
  actionPending.value = user.id
  try {
    const updated = await updateUserRole(user.id, { role: newRole })
    const idx = users.value.findIndex((u) => u.id === user.id)
    if (idx !== -1) users.value[idx] = updated
    showSuccess(`已将「${user.username}」${newRole === 'admin' ? '设为管理员' : '降为普通用户'}`)
  } catch (error: any) {
    showError(error?.message || '角色修改失败')
  } finally {
    actionPending.value = null
  }
}

const openDeleteDialog = (user: UserResponse) => {
  pendingDeleteUser.value = user
  showDeleteDialog.value = true
}

const confirmDelete = async () => {
  if (!pendingDeleteUser.value) return
  const target = pendingDeleteUser.value
  actionPending.value = target.id
  try {
    await deleteUser(target.id)
    users.value = users.value.filter((u) => u.id !== target.id)
    showSuccess(`用户「${target.username}」已删除`)
  } catch (error: any) {
    showError(error?.message || '删除失败')
  } finally {
    actionPending.value = null
    pendingDeleteUser.value = null
  }
}

onMounted(loadUsers)
</script>

<style scoped lang="scss">
.user-manage-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #f8f9fa;
  padding: 32px 32px 24px;
  box-sizing: border-box;
  overflow: auto;
}

.user-manage-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  flex-shrink: 0;
}

.user-manage-header__left {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.user-manage-header__title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #202124;
}

.user-manage-header__count {
  font-size: 13px;
  color: #9aa0a6;
}

.refresh-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 16px;
  border: 1px solid #dadce0;
  border-radius: 8px;
  background: #ffffff;
  color: #5f6368;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;

  &:hover:not(:disabled) {
    background: #f1f3f4;
    border-color: #bdc1c6;
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
}

.refresh-btn__icon {
  font-size: 16px;
  display: inline-block;
  transition: transform 0.5s ease;

  &.is-spinning {
    animation: spin 0.8s linear infinite;
  }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.user-manage-content {
  background: #ffffff;
  border-radius: 12px;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.08);
  overflow: hidden;
  flex: 1;
}

.state-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 160px;
  font-size: 14px;
  color: #9aa0a6;
}

.user-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
  color: #202124;
}

.user-table__th {
  padding: 12px 16px;
  text-align: left;
  font-size: 12px;
  font-weight: 600;
  color: #5f6368;
  background: #f8f9fa;
  border-bottom: 1px solid #e8eaed;
  white-space: nowrap;

  &--actions {
    text-align: right;
  }
}

.user-table__row {
  transition: background 0.15s ease;

  &:not(:last-child) {
    border-bottom: 1px solid #f1f3f4;
  }

  &:hover {
    background: #f8f9fa;
  }
}

.user-table__td {
  padding: 14px 16px;
  vertical-align: middle;

  &--username {
    font-weight: 500;
    color: #202124;
  }

  &--email {
    color: #5f6368;
    font-size: 13px;
  }

  &--actions {
    text-align: right;
    white-space: nowrap;
  }
}

.role-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;

  &--superuser {
    background: #e8f0fe;
    color: #1a73e8;
  }

  &--admin {
    background: #e6f4ea;
    color: #137333;
  }

  &--user {
    background: #f1f3f4;
    color: #5f6368;
  }
}

.action-btn {
  height: 30px;
  padding: 0 12px;
  border-radius: 6px;
  border: 1px solid transparent;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, opacity 0.15s ease;

  & + & {
    margin-left: 8px;
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  &--role {
    background: #e8f0fe;
    color: #1a73e8;
    border-color: #d2e3fc;

    &:hover:not(:disabled) {
      background: #d2e3fc;
    }
  }

  &--delete {
    background: #fce8e6;
    color: #c5221f;
    border-color: #f5c6c4;

    &:hover:not(:disabled) {
      background: #f5c6c4;
    }
  }
}

.self-label {
  font-size: 12px;
  color: #9aa0a6;
  font-style: italic;
}
</style>

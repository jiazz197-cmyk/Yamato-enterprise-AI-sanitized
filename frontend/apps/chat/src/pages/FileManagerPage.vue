<template>
  <div class="file-manager-page">
    <div class="file-manager-header">
      <div class="file-manager-header__left">
        <h1 class="file-manager-header__title">文件管理</h1>
        <span class="file-manager-header__count">共 {{ tasks.length }} 个任务</span>
      </div>
      <div class="header-actions">
        <div class="ws-metric">
          <span class="ws-metric__label">WebSocket 连接数:</span>
          <span class="ws-metric__value">{{ wsConnections }}</span>
        </div>
        <button class="upload-btn" @click="handleUpload">
          上传文件
        </button>
      </div>
    </div>

    <div class="file-manager-content">
      <div class="task-list">
        <TaskCard
          v-for="task in sortedTasks"
          :key="task.id"
          :title="task.name"
          :status="task.status"
          :progress="task.progress"
          @refresh="handleRefresh(task.id)"
          @cancel="handleCancel(task.id)"
          @delete="handleDelete(task.id)"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Button, TaskCard, PageHeader } from '@yamato/components'

type TaskStatus = 'in_progress' | 'cancelled' | 'completed'

interface TaskItem {
  id: string
  name: string
  status: TaskStatus
  progress: number
}

const wsConnections = ref(0)
let wsTimer: number | null = null

const randInt = (min: number, max: number) => {
  const low = Math.min(min, max)
  const high = Math.max(min, max)
  return Math.floor(low + Math.random() * (high - low + 1))
}

const createId = () => `task_${Date.now()}_${Math.random().toString(16).slice(2)}`

const createRandomTask = (): TaskItem => {
  const pool: TaskStatus[] = ['in_progress', 'cancelled', 'completed']
  const status = pool[randInt(0, pool.length - 1)]
  const progressBase = randInt(0, 95)

  return {
    id: createId(),
    name: `文档处理任务 #${randInt(1000, 9999)}`,
    status,
    progress: status === 'completed' ? 100 : progressBase,
  }
}

const tasks = ref<TaskItem[]>(Array.from({ length: 8 }).map(() => createRandomTask()))

const statusRank = (s: TaskStatus) => {
  if (s === 'in_progress') return 0
  if (s === 'cancelled') return 1
  return 2
}

const sortedTasks = computed(() => {
  return [...tasks.value].sort((a, b) => {
    const diff = statusRank(a.status) - statusRank(b.status)
    if (diff !== 0) return diff
    return a.name.localeCompare(b.name)
  })
})

const handleUpload = () => {
  tasks.value.unshift({
    id: createId(),
    name: `上传处理任务 #${randInt(1000, 9999)}`,
    status: 'in_progress',
    progress: randInt(0, 15),
  })
}

const handleRefresh = (id: string) => {
  const task = tasks.value.find((t) => t.id === id)
  if (!task) return

  if (task.status === 'cancelled') return
  if (task.status === 'completed') return

  task.progress = Math.min(99, Math.max(task.progress, randInt(task.progress, task.progress + randInt(3, 18))))
  if (task.progress >= 95 && Math.random() > 0.6) {
    task.status = 'completed'
    task.progress = 100
  }
}

const handleCancel = (id: string) => {
  const task = tasks.value.find((t) => t.id === id)
  if (!task) return
  if (task.status !== 'in_progress') return
  task.status = 'cancelled'
}

const handleDelete = (id: string) => {
  tasks.value = tasks.value.filter((t) => t.id !== id)
}

onMounted(() => {
  wsConnections.value = randInt(1, 20)
  wsTimer = window.setInterval(() => {
    wsConnections.value = randInt(0, 40)
  }, 1200)
})

onUnmounted(() => {
  if (wsTimer !== null) {
    window.clearInterval(wsTimer)
    wsTimer = null
  }
})
</script>

<style scoped lang="scss">
.file-manager-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 32px 32px 24px;
  box-sizing: border-box;
  overflow: auto;
}

.file-manager-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  flex-shrink: 0;
}

.file-manager-header__left {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.file-manager-header__title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #202124;
}

.file-manager-header__count {
  font-size: 13px;
  color: #9aa0a6;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 20px;
}

.ws-metric {
  display: flex;
  align-items: baseline;
  gap: 6px;
  user-select: none;
}

.ws-metric__label {
  font-size: 12px;
  color: #5f6368;
}

.ws-metric__value {
  font-size: 14px;
  font-weight: 600;
  color: #202124;
}

.upload-btn {
  height: 36px;
  padding: 0 16px;
  background: #1a73e8;
  color: #ffffff;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s ease;

  &:hover {
    background: #1765cf;
  }
}

.file-manager-content {
  background: #ffffff;
  border-radius: 12px;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.08);
  padding: 24px;
  flex: 1;
}

.task-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
  align-items: start;
}
</style>


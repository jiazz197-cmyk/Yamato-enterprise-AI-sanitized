<template>
  <div class="page">
    <PageHeader title="文件管理" subtitle="上传、浏览与管理你的文件" />

    <div class="page__content">
      <div class="toolbar">
        <Button variant="primary" @click="handleUpload">上传文件</Button>
        <div class="toolbar__right">
          <div class="ws-metric">
            <div class="ws-metric__label">WebSocket 连接数</div>
            <div class="ws-metric__value">{{ wsConnections }}</div>
          </div>
        </div>
      </div>

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
.page {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.page__content {
  flex: 1;
  overflow: auto;
  padding: 24px 32px;
  background: #ffffff;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.toolbar__right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}

.ws-metric {
  text-align: right;
  user-select: none;
}

.ws-metric__label {
  font-size: 12px;
  color: #5f6368;
  line-height: 1.2;
}

.ws-metric__value {
  margin-top: 2px;
  font-size: 18px;
  font-weight: 700;
  color: #202124;
  line-height: 1.2;
}

.task-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
  align-items: start;
}
</style>


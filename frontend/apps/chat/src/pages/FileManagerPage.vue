<template>
  <div class="quotation-page">
    <input
      ref="fileInputRef"
      class="hidden-input"
      type="file"
      accept="application/pdf,.pdf"
      @change="handleFileSelected"
    />

    <header class="quotation-header">
      <div>
        <h1 class="quotation-title">报价生成</h1>
        <p class="quotation-subtitle">
          共 {{ tasks.length }} 个任务 · WebSocket 连接 {{ wsConnections }} 个
        </p>
      </div>
      <div class="header-actions">
        <button class="secondary-btn" :disabled="loading" @click="() => loadTasks()">
          刷新
        </button>
        <button class="primary-btn" :disabled="uploading" @click="openFilePicker">
          {{ uploading ? '上传中...' : '上传PDF' }}
        </button>
      </div>
    </header>

    <p v-if="errorMessage" class="error-tip">{{ errorMessage }}</p>

    <section class="columns">
      <article class="column">
        <header class="column-header">
          <h2>排队任务</h2>
          <span>{{ queuedTasks.length }}</span>
        </header>
        <div v-if="queuedTasks.length === 0" class="empty">暂无排队任务</div>
        <TaskItemCard
          v-for="task in queuedTasks"
          :key="task.task_id"
          :task="task"
          :show-owner="true"
          :can-cancel="canCancel(task)"
          :can-delete="false"
          @cancel="handleCancel(task.task_id)"
          @view-result="openResultModal(task)"
          @view-file="handleViewFile(task.task_id)"
          @download-u8-xlsx="handleDownloadU8Xlsx(task.task_id)"
        />
      </article>

      <article class="column">
        <header class="column-header">
          <h2>处理中任务</h2>
          <span>{{ runningTasks.length }}</span>
        </header>
        <div v-if="runningTasks.length === 0" class="empty">暂无处理中任务</div>
        <TaskItemCard
          v-for="task in runningTasks"
          :key="task.task_id"
          :task="task"
          :show-owner="true"
          :can-cancel="canCancel(task)"
          :can-delete="false"
          :is-approving="approvingTasks.has(task.task_id)"
          @cancel="handleCancel(task.task_id)"
          @approve="(partids: string[]) => handleApprove(task.task_id, partids)"
          @view-result="openResultModal(task)"
          @view-file="handleViewFile(task.task_id)"
          @download-u8-xlsx="handleDownloadU8Xlsx(task.task_id)"
        />
      </article>

      <article class="column column--done">
        <header class="column-header">
          <h2>完成任务</h2>
          <span>{{ doneTasks.length }}</span>
        </header>
        <p class="dev-tip">该功能仍在开发中，非最终版</p>
        <div class="task-list task-list--scroll">
          <div v-if="doneTasks.length === 0" class="empty">暂无完成任务</div>
          <TaskItemCard
            v-for="task in doneTasks"
            :key="task.task_id"
            :task="task"
            :show-owner="true"
            :can-cancel="false"
            :can-delete="canDelete(task)"
            @cancel="handleCancel(task.task_id)"
            @delete="handleDelete(task.task_id)"
            @view-result="openResultModal(task)"
            @view-file="handleViewFile(task.task_id)"
            @download-u8-xlsx="handleDownloadU8Xlsx(task.task_id)"
          />
        </div>
      </article>
    </section>

    <div v-if="resultModalVisible" class="result-modal-mask" @click.self="closeResultModal">
      <div class="result-modal">
        <div class="result-modal__header">
          <h3>任务结果：{{ selectedTask?.display_name || selectedTask?.uploaded_file_name }}</h3>
          <button class="icon-btn" @click="closeResultModal">关闭</button>
        </div>
        <div class="result-modal__content">
          <p><strong>任务ID：</strong>{{ selectedTask?.task_id }}</p>
          <p><strong>状态：</strong>{{ selectedTask?.status }}</p>
          <p><strong>消息：</strong>{{ selectedTask?.message }}</p>
          <p v-if="isCompactResult" class="result-compact-tip">
            当前显示的是轻量摘要，完整 U8 明细请下载 Excel 查看。
          </p>
          <pre class="result-json">{{ formattedResult }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, onUnmounted, ref, watch } from 'vue'
import { config } from '../config'
import type { QuotationPdmItem, QuotationPdmResult, QuotationTaskItem } from '../types/quotation'
import {
  approveQuotationTask,
  cancelQuotationTask,
  createQuotationTask,
  deleteQuotationTask,
  downloadQuotationTaskFile,
  downloadQuotationU8ByTypeWorkbook,
  getQuotationTask,
  listQuotationTasks,
} from '../services/quotation'
import { createTaskWebSocket } from '../services/ws'

const fileInputRef = ref<HTMLInputElement | null>(null)
const tasks = ref<QuotationTaskItem[]>([])
const loading = ref(false)
const uploading = ref(false)
const errorMessage = ref('')
const wsConnections = ref(0)
const selectedTask = ref<QuotationTaskItem | null>(null)
const resultModalVisible = ref(false)

const wsMap = new Map<string, WebSocket>()
const wsTaskEpochMap = new Map<string, number>()
const wsConnectQueue: string[] = []
const wsConnectQueuedTaskIds = new Set<string>()
let wsConnectBatchTimer: number | null = null
const refreshTimers = new Map<string, number>()
const refreshInFlightTaskIds = new Set<string>()
const refreshQueuedTaskIds = new Set<string>()
const approvalDetailRequestedTaskIds = new Set<string>()
let loadTasksAbortController: AbortController | null = null
let loadTasksTimeoutId: number | null = null
let isPageUnmounted = false

const wsDisabledUntilByTaskId = new Map<string, number>()
const taskPollingTimerByTaskId = new Map<string, number>()
const taskSyncModeByTaskId = new Map<string, 'ws' | 'polling'>()
const wsFailureCountByTaskId = new Map<string, number>()
const wsExpectedCloseReasonsByTaskId = new Map<string, string>()

let listRefreshTimerId: number | null = null
let listRefreshBackoffMultiplier = 1
let listRefreshSuccessiveFailures = 0

const ACTIVE_STATUSES: string[] = ['queued', 'running', 'awaiting_approval']
const TERMINAL_STATUSES: string[] = ['completed', 'failed', 'cancelled']
const ENABLE_TASK_WEBSOCKET = true
const DEBUG_FILE_MANAGER_DIAGNOSTICS = true
const WS_CONNECT_BATCH_SIZE = 4
const WS_CONNECT_BATCH_INTERVAL_MS = 100
const UPLOAD_CREATE_TASK_PENDING_WARN_MS = 20000
const WS_FAILURE_WINDOW_MS = 30000
const WS_FAILURE_WARN_COUNT = 6
const WS_QUEUE_WARN_LENGTH = 12
const EVENT_LOOP_LAG_SAMPLE_INTERVAL_MS = 1000
const EVENT_LOOP_LAG_WARN_MS = 250
const WS_COOLDOWN_MS = 60000
const WS_MAX_PER_TASK_FAILURES = 2
const TASK_POLLING_INTERVAL_MS = 4000
const LIST_REFRESH_NORMAL_MS = 60000
const LIST_REFRESH_BACKOFF_1_MS = 90000
const LIST_REFRESH_BACKOFF_2_MS = 120000
const LIST_REFRESH_BACKOFF_MAX_MS = 180000

let loadTasksRequestSeq = 0
let loadTasksActiveSeq = 0
let uploadAttemptSeq = 0
let stateEpoch = 0
let wsConnectAttemptSeq = 0
let wsConnectFailureSeq = 0
let wsConsecutiveFailures = 0
let wsMaxQueueLengthSeen = 0
let loadTasksAbortErrorCount = 0
let loadTasksForceAbortCount = 0
let loadTasksSkipWhileLoadingCount = 0
let loadTasksInFlightRequestId: number | null = null
let eventLoopLagProbeTimer: number | null = null
let eventLoopLagProbeLastTickMs = 0
let eventLoopLagWarnCount = 0
const wsFailureTimestamps: number[] = []

const logDiag = (event: string, details?: Record<string, unknown>): void => {
  if (!DEBUG_FILE_MANAGER_DIAGNOSTICS) return
  try {
    console.info('[FileManagerDiag]', {
      event,
      ts: new Date().toISOString(),
      route: window.location.pathname,
      tasks: tasks.value.length,
      wsConnections: wsMap.size,
      loading: loading.value,
      ...details,
    })
  } catch {
    // ignore logging failures
  }
}

const logDiagError = (event: string, error: unknown, details?: Record<string, unknown>): void => {
  if (!DEBUG_FILE_MANAGER_DIAGNOSTICS) return
  try {
    const cast = error as { message?: string; stack?: string; name?: string }
    console.error('[FileManagerDiagError]', {
      event,
      ts: new Date().toISOString(),
      route: window.location.pathname,
      tasks: tasks.value.length,
      wsConnections: wsMap.size,
      loading: loading.value,
      errorName: cast?.name,
      errorMessage: cast?.message,
      errorStack: cast?.stack,
      ...details,
    })
  } catch {
    // ignore logging failures
  }
}

const logDiagCritical = (event: string, details?: Record<string, unknown>): void => {
  if (!DEBUG_FILE_MANAGER_DIAGNOSTICS) return
  try {
    console.error('[FileManagerDiagCritical]', {
      event,
      ts: new Date().toISOString(),
      route: window.location.pathname,
      tasks: tasks.value.length,
      wsConnections: wsMap.size,
      loading: loading.value,
      ...details,
    })
  } catch {
    // ignore logging failures
  }
}

const getArrayLength = (value: unknown): number => (Array.isArray(value) ? value.length : 0)

const getObjectKeyCount = (value: unknown): number => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return 0
  return Object.keys(value as Record<string, unknown>).length
}

const computeApproxJsonSize = (value: unknown): number | null => {
  try {
    return JSON.stringify(value).length
  } catch {
    return null
  }
}

const logPhase2ResultSnapshot = (task: QuotationTaskItem, source: string): void => {
  const result = task.result
  if (!result || typeof result !== 'object') return

  const keywordsPayload = (result as { keywords_payload?: unknown }).keywords_payload
  const keywords =
    keywordsPayload && typeof keywordsPayload === 'object'
      ? (keywordsPayload as { keywords?: unknown }).keywords
      : undefined
  const pdmItems = result.pdm_result?.items
  const queryIndexSet = new Set<number>()

  if (Array.isArray(pdmItems)) {
    pdmItems.forEach((item) => {
      const value: unknown = item?.QUERY_INDEX
      if (typeof value === 'number' && Number.isFinite(value)) queryIndexSet.add(Math.trunc(value))
      if (typeof value === 'string') {
        const parsed = Number.parseInt(value.trim(), 10)
        if (Number.isFinite(parsed)) queryIndexSet.add(parsed)
      }
    })
  }

  logDiag('phase2_result_snapshot', {
    source,
    taskId: task.task_id,
    status: task.status,
    isCompact: Boolean(result.__result_compact),
    isOmitted: Boolean(result.__result_omitted),
    keywordCount: getArrayLength(keywords),
    pdmItemCount: getArrayLength(pdmItems),
    pdmDistinctQueryIndexCount: queryIndexSet.size,
    pdmDeclaredTotal: typeof result.pdm_result?.total === 'number' ? result.pdm_result.total : null,
    approvedPartidsCount: getArrayLength(result.approved_partids),
    pdmPartidsCount: getArrayLength(result.pdm_partids),
    u8ByTypeCount: getArrayLength(result.u8_result_by_type?.items),
    u8ByTypeSummaryTypeCount: getArrayLength(result.u8_result_type_summary?.types),
    u8ByTypeSummaryMappingCount: getArrayLength(result.u8_result_type_summary?.mapping),
    rawExtractedInfoKeyCount: getObjectKeyCount(result.raw_extracted_info),
    resultApproxJsonChars: computeApproxJsonSize(result),
  })
}

const pruneWsFailureTimestamps = (nowMs: number): void => {
  while (wsFailureTimestamps.length > 0 && nowMs - wsFailureTimestamps[0] > WS_FAILURE_WINDOW_MS) {
    wsFailureTimestamps.shift()
  }
}

const recordWsQueuePressure = (source: string): void => {
  const queueLength = wsConnectQueue.length
  if (queueLength > wsMaxQueueLengthSeen) {
    wsMaxQueueLengthSeen = queueLength
    logDiag('ws_queue_new_peak', {
      source,
      queueLength,
      maxQueueLengthSeen: wsMaxQueueLengthSeen,
      queuedTaskIds: wsConnectQueue.slice(0, 8),
    })
  }

  if (queueLength >= WS_QUEUE_WARN_LENGTH) {
    logDiag('ws_queue_pressure_warn', {
      source,
      queueLength,
      activeConnections: wsMap.size,
      activeTasks: tasks.value.filter((task) => ACTIVE_STATUSES.includes(task.status)).length,
      queuedTaskIds: wsConnectQueue.slice(0, 12),
    })
  }
}

const recordWsFailure = (source: string, taskId: string, error?: unknown): void => {
  const nowMs = Date.now()
  wsConnectFailureSeq += 1
  wsConsecutiveFailures += 1
  wsFailureTimestamps.push(nowMs)
  pruneWsFailureTimestamps(nowMs)

  const prevCount = wsFailureCountByTaskId.get(taskId) ?? 0
  const newCount = prevCount + 1
  wsFailureCountByTaskId.set(taskId, newCount)

  logDiagError('ws_failure_observed', error ?? new Error('ws connection failure'), {
    source,
    taskId,
    failureSeq: wsConnectFailureSeq,
    consecutiveFailures: wsConsecutiveFailures,
    perTaskFailureCount: newCount,
    perTaskThreshold: WS_MAX_PER_TASK_FAILURES,
    failuresInWindow: wsFailureTimestamps.length,
    failureWindowMs: WS_FAILURE_WINDOW_MS,
    queueLength: wsConnectQueue.length,
    connections: wsMap.size,
  })

  if (wsFailureTimestamps.length >= WS_FAILURE_WARN_COUNT) {
    logDiag('ws_failure_burst_detected', {
      source,
      taskId,
      failuresInWindow: wsFailureTimestamps.length,
      failureWindowMs: WS_FAILURE_WINDOW_MS,
      consecutiveFailures: wsConsecutiveFailures,
    })
  }

  if (newCount >= WS_MAX_PER_TASK_FAILURES) {
    const cooldownUntil = nowMs + WS_COOLDOWN_MS
    wsDisabledUntilByTaskId.set(taskId, cooldownUntil)
    switchTaskSyncMode(taskId, 'polling', 'ws_cooldown_after_failures')
    closeSocket(taskId, 'ws_cooldown')
    logDiagCritical('ws_task_cooldown_activated', {
      taskId,
      perTaskFailureCount: newCount,
      cooldownUntil,
      cooldownMs: WS_COOLDOWN_MS,
      syncMode: taskSyncModeByTaskId.get(taskId),
    })
  }
}

const recordWsConnectSuccess = (taskId: string): void => {
  const nowMs = Date.now()
  pruneWsFailureTimestamps(nowMs)
  if (wsConsecutiveFailures > 0) {
    logDiag('ws_recovered_after_failures', {
      taskId,
      consecutiveFailuresBeforeRecovery: wsConsecutiveFailures,
      failuresStillInWindow: wsFailureTimestamps.length,
    })
  }
  wsConsecutiveFailures = 0
  wsFailureCountByTaskId.delete(taskId)
  wsDisabledUntilByTaskId.delete(taskId)
}

const recordWsHandshakeSuccess = (taskId: string): void => {
  recordWsConnectSuccess(taskId)
}

const switchTaskSyncMode = (taskId: string, newMode: 'ws' | 'polling', reason: string): void => {
  const oldMode = taskSyncModeByTaskId.get(taskId) ?? 'ws'
  if (oldMode === newMode) return
  taskSyncModeByTaskId.set(taskId, newMode)
  logDiagCritical('task_sync_mode_changed', {
    taskId,
    oldMode,
    newMode,
    reason,
  })
  if (newMode === 'polling') {
    startTaskPolling(taskId)
    logDiagCritical('task_sync_mode_ws_to_polling', { taskId, reason })
  } else {
    stopTaskPolling(taskId)
    wsDisabledUntilByTaskId.delete(taskId)
    wsFailureCountByTaskId.delete(taskId)
    logDiagCritical('task_sync_mode_polling_to_ws', { taskId, reason })
  }
}

const startTaskPolling = (taskId: string): void => {
  if (taskPollingTimerByTaskId.has(taskId)) return
  const task = tasks.value.find((t) => t.task_id === taskId)
  if (!task) return
  if (!ACTIVE_STATUSES.includes(task.status)) return

  logDiagCritical('task_polling_started', {
    taskId,
    status: task.status,
    intervalMs: TASK_POLLING_INTERVAL_MS,
  })
  taskPollingTick(taskId)
}

const stopTaskPolling = (taskId: string): void => {
  const timer = taskPollingTimerByTaskId.get(taskId)
  if (timer !== undefined) {
    window.clearTimeout(timer)
    taskPollingTimerByTaskId.delete(taskId)
  }
  taskSyncModeByTaskId.delete(taskId)
  logDiagCritical('task_polling_stopped', { taskId })
}

const TASK_POLLING_BACKOFF_MAX_MS = 30000
const TASK_POLLING_429_BACKOFF_MULTIPLIER = 2

const taskPollingTick = (taskId: string, backoffMs?: number): void => {
  if (isPageUnmounted) return
  const task = tasks.value.find((t) => t.task_id === taskId)
  if (!task) {
    stopTaskPolling(taskId)
    return
  }
  if (!ACTIVE_STATUSES.includes(task.status)) {
    stopTaskPolling(taskId)
    closeSocket(taskId, 'task_polling_terminal')
    return
  }
  if (taskSyncModeByTaskId.get(taskId) !== 'polling') return

  const effectiveInterval = typeof backoffMs === 'number' && backoffMs > 0
    ? backoffMs
    : TASK_POLLING_INTERVAL_MS

  logDiag('task_polling_tick', { taskId, status: task.status, backoffMs: effectiveInterval })
  const epoch = stateEpoch
  getQuotationTask(taskId)
    .then((task) => {
      applyTaskUpsertById(task, { epoch, source: 'task_polling_tick' })
      if (TERMINAL_STATUSES.includes(task.status)) {
        stopTaskPolling(taskId)
        return
      }
      taskPollingTimerByTaskId.set(
        taskId,
        window.setTimeout(() => taskPollingTick(taskId, TASK_POLLING_INTERVAL_MS), TASK_POLLING_INTERVAL_MS)
      )
    })
    .catch((error: unknown) => {
      const is429 = (error as { status?: number })?.status === 429
        || String((error as { message?: string })?.message ?? '').includes('过于频繁')
      const nextBackoff = is429
        ? Math.min(
            effectiveInterval * TASK_POLLING_429_BACKOFF_MULTIPLIER,
            TASK_POLLING_BACKOFF_MAX_MS
          )
        : effectiveInterval
      logDiagCritical('task_polling_tick_failed', {
        taskId,
        is429,
        backoffMs: effectiveInterval,
        nextBackoffMs: nextBackoff,
        errorMessage: (error as { message?: string })?.message ?? '',
      })
      taskPollingTimerByTaskId.set(
        taskId,
        window.setTimeout(() => taskPollingTick(taskId, nextBackoff), nextBackoff)
      )
    })
}

const getNavigatorOnline = (): boolean | null => {
  if (typeof navigator === 'undefined') return null
  return typeof navigator.onLine === 'boolean' ? navigator.onLine : null
}

const getUserAgent = (): string => {
  if (typeof navigator === 'undefined') return ''
  return String(navigator.userAgent ?? '')
}

const logPageEnvironment = (event: string, details?: Record<string, unknown>): void => {
  logDiag(event, {
    visibilityState: document.visibilityState,
    online: getNavigatorOnline(),
    hasFocus: typeof document.hasFocus === 'function' ? document.hasFocus() : null,
    userAgent: getUserAgent(),
    ...details,
  })
}

const getWebSocketReadyStateLabel = (socket: WebSocket | null | undefined): string => {
  if (!socket) return 'missing'
  if (socket.readyState === WebSocket.CONNECTING) return 'connecting'
  if (socket.readyState === WebSocket.OPEN) return 'open'
  if (socket.readyState === WebSocket.CLOSING) return 'closing'
  if (socket.readyState === WebSocket.CLOSED) return 'closed'
  return `unknown_${socket.readyState}`
}

const describeWebSocket = (socket: WebSocket | null | undefined): Record<string, unknown> => ({
  readyState: socket?.readyState ?? null,
  readyStateLabel: getWebSocketReadyStateLabel(socket),
  bufferedAmount: socket?.bufferedAmount ?? null,
  protocol: socket?.protocol ?? '',
  extensions: socket?.extensions ?? '',
  url: socket?.url ?? '',
})

const startEventLoopLagProbe = (): void => {
  if (eventLoopLagProbeTimer !== null) return
  eventLoopLagProbeLastTickMs = Date.now()

  eventLoopLagProbeTimer = window.setInterval(() => {
    const nowMs = Date.now()
    const elapsedMs = nowMs - eventLoopLagProbeLastTickMs
    eventLoopLagProbeLastTickMs = nowMs
    const lagMs = elapsedMs - EVENT_LOOP_LAG_SAMPLE_INTERVAL_MS

    if (lagMs >= EVENT_LOOP_LAG_WARN_MS) {
      eventLoopLagWarnCount += 1
      logDiag('event_loop_lag_warn', {
        lagMs,
        elapsedMs,
        warnCount: eventLoopLagWarnCount,
        queueLength: wsConnectQueue.length,
        wsConnections: wsMap.size,
        taskCount: tasks.value.length,
        visibilityState: document.visibilityState,
      })
    }
  }, EVENT_LOOP_LAG_SAMPLE_INTERVAL_MS)

  logDiag('event_loop_lag_probe_started', {
    sampleIntervalMs: EVENT_LOOP_LAG_SAMPLE_INTERVAL_MS,
    warnThresholdMs: EVENT_LOOP_LAG_WARN_MS,
  })
}

const stopEventLoopLagProbe = (): void => {
  if (eventLoopLagProbeTimer === null) return
  window.clearInterval(eventLoopLagProbeTimer)
  eventLoopLagProbeTimer = null
  logDiag('event_loop_lag_probe_stopped', {
    warnCount: eventLoopLagWarnCount,
  })
}

const handleWindowError = (event: ErrorEvent): void => {
  logDiagError('window_error', event.error ?? new Error(event.message), {
    message: event.message,
    filename: event.filename,
    lineno: event.lineno,
    colno: event.colno,
  })
}

const handleUnhandledRejection = (event: PromiseRejectionEvent): void => {
  const reason = event.reason as { message?: string; stack?: string; name?: string } | undefined
  logDiagError('window_unhandled_rejection', reason ?? event.reason, {
    reasonType: typeof event.reason,
  })
}

const handleVisibilityChange = (): void => {
  logPageEnvironment('page_visibility_changed')
  if (document.visibilityState === 'visible') {
    triggerResumeSync('visibility_change')
  }
}

const handleOnline = (): void => {
  logPageEnvironment('page_online_state_changed', {
    onlineEvent: 'online',
  })
  triggerResumeSync('online')
}

const handleOffline = (): void => {
  logPageEnvironment('page_online_state_changed', {
    onlineEvent: 'offline',
  })
}

const handleFocus = (): void => {
  logPageEnvironment('page_focus_changed', {
    focusEvent: 'focus',
  })
  triggerResumeSync('focus')
}

const handleBlur = (): void => {
  logPageEnvironment('page_focus_changed', {
    focusEvent: 'blur',
  })
}

const readUserRole = (): string => {
  try {
    const raw = localStorage.getItem(config.settingsStorageKey)
    if (!raw) return ''
    const parsed = JSON.parse(raw) as { role?: unknown }
    return String(parsed.role ?? '').trim()
  } catch {
    return ''
  }
}

const currentRole = ref(readUserRole())

const statusOrder = (status: string): number => {
  if (status === 'running') return 0
  if (status === 'awaiting_approval') return 1
  if (status === 'queued') return 2
  if (status === 'completed') return 3
  if (status === 'failed') return 4
  return 5
}

const approvingTasks = ref<Set<string>>(new Set())

const byDateAsc = (a: QuotationTaskItem, b: QuotationTaskItem) => {
  return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
}

const byDateDesc = (a: QuotationTaskItem, b: QuotationTaskItem) => {
  return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
}

const queuedTasks = computed(() => {
  return tasks.value
    .filter((task) => task.status === 'queued')
    .sort(byDateAsc)
})

const runningTasks = computed(() => {
  return tasks.value
    .filter((task) => task.status === 'running' || task.status === 'awaiting_approval')
    .sort(byDateAsc)
})

const doneTasks = computed(() => {
  return tasks.value
    .filter((task) => ['completed', 'failed', 'cancelled'].includes(task.status))
    .sort(byDateDesc)
})

const compactJsonValue = (value: unknown, depth = 0): unknown => {
  if (depth >= 4) return '[Object]'
  if (!value || typeof value !== 'object') return value

  if (Array.isArray(value)) {
    const preview = value.slice(0, 20).map((item) => compactJsonValue(item, depth + 1))
    if (value.length > preview.length) {
      preview.push(`... ${value.length - preview.length} more items`)
    }
    return preview
  }

  const source = value as Record<string, unknown>
  const result: Record<string, unknown> = {}
  Object.entries(source).forEach(([key, item]) => {
    result[key] = compactJsonValue(item, depth + 1)
  })
  return result
}

const isCompactResult = computed(() => {
  return Boolean(selectedTask.value?.result?.__result_compact)
})

const formattedResult = computed(() => {
  if (!selectedTask.value?.result) {
    return '暂无结果数据'
  }
  return JSON.stringify(compactJsonValue(selectedTask.value.result), null, 2)
})

const syncWsConnections = (): void => {
  wsConnections.value = wsMap.size
}

const isCurrentEpoch = (epoch?: number): boolean => {
  if (epoch === undefined) return true
  return epoch === stateEpoch
}

const guardEpoch = (epoch: number | undefined, source: string, details?: Record<string, unknown>): boolean => {
  if (isCurrentEpoch(epoch)) return true
  logDiag('state_epoch_discard', {
    source,
    receivedEpoch: epoch,
    currentEpoch: stateEpoch,
    ...details,
  })
  return false
}

const sortTasksByStatus = (items: QuotationTaskItem[]): QuotationTaskItem[] => {
  return [...items].sort((a, b) => statusOrder(a.status) - statusOrder(b.status))
}

const mergeTaskListItem = (
  incoming: QuotationTaskItem,
  existing?: QuotationTaskItem
): QuotationTaskItem => {
  if (incoming.result?.__result_omitted && existing?.result && !existing.result.__result_omitted) {
    return {
      ...incoming,
      result: existing.result,
    }
  }
  return incoming
}

const syncSelectedTaskRef = (): void => {
  const selectedTaskId = selectedTask.value?.task_id
  if (!selectedTaskId) return
  const next = tasks.value.find((task) => task.task_id === selectedTaskId) ?? null
  selectedTask.value = next
}

const applyTaskListSnapshot = (incomingTasks: QuotationTaskItem[], options?: { epoch?: number; source?: string }): boolean => {
  if (!guardEpoch(options?.epoch, options?.source ?? 'apply_task_list_snapshot')) {
    return false
  }

  const existingById = new Map(tasks.value.map((task) => [task.task_id, task]))
  const nextTasks = incomingTasks.map((incoming) =>
    mergeTaskListItem(incoming, existingById.get(incoming.task_id))
  )
  tasks.value = sortTasksByStatus(nextTasks)
  syncSelectedTaskRef()

  nextTasks
    .filter((task) => Boolean(task.result) && (task.status === 'awaiting_approval' || task.status === 'completed'))
    .slice(0, 20)
    .forEach((task) => {
      logPhase2ResultSnapshot(task, options?.source ?? 'apply_task_list_snapshot')
    })

  return true
}

const applyTaskPatchById = (
  taskId: string,
  buildNext: (current: QuotationTaskItem) => QuotationTaskItem,
  options?: { epoch?: number; source?: string }
): QuotationTaskItem | null => {
  if (!guardEpoch(options?.epoch, options?.source ?? 'apply_task_patch', { taskId })) {
    return null
  }

  const index = tasks.value.findIndex((task) => task.task_id === taskId)
  if (index < 0) return null

  const current = tasks.value[index]
  const next = buildNext(current)
  const nextTasks = [...tasks.value]
  nextTasks[index] = next
  tasks.value = sortTasksByStatus(nextTasks)

  if (selectedTask.value?.task_id === taskId) {
    selectedTask.value = next
  }

  return next
}

const applyTaskUpsertById = (
  incoming: QuotationTaskItem,
  options?: { epoch?: number; source?: string }
): QuotationTaskItem | null => {
  if (!guardEpoch(options?.epoch, options?.source ?? 'apply_task_upsert', {
    taskId: incoming.task_id,
  })) {
    return null
  }

  const index = tasks.value.findIndex((task) => task.task_id === incoming.task_id)
  const existing = index >= 0 ? tasks.value[index] : undefined
  const merged = mergeTaskListItem(incoming, existing)
  const nextTasks = [...tasks.value]

  if (index < 0) {
    nextTasks.unshift(merged)
  } else {
    nextTasks[index] = merged
  }

  tasks.value = sortTasksByStatus(nextTasks)

  if (selectedTask.value?.task_id === incoming.task_id) {
    selectedTask.value = merged
  }

  if (merged.result && (merged.status === 'awaiting_approval' || merged.status === 'completed')) {
    logPhase2ResultSnapshot(merged, options?.source ?? 'apply_task_upsert')
  }

  return merged
}

const hasApprovalItems = (task: QuotationTaskItem): boolean => {
  const items = task.result?.pdm_result?.items
  return Array.isArray(items) && items.length > 0
}

const removeQueuedTaskSocket = (taskId: string): void => {
  const queueIndex = wsConnectQueue.indexOf(taskId)
  if (queueIndex >= 0) {
    wsConnectQueue.splice(queueIndex, 1)
  }
  wsConnectQueuedTaskIds.delete(taskId)
}

const clearWsConnectScheduler = (): void => {
  if (wsConnectBatchTimer !== null) {
    window.clearTimeout(wsConnectBatchTimer)
    wsConnectBatchTimer = null
  }
  wsConnectQueue.forEach((taskId) => {
    wsTaskEpochMap.delete(taskId)
  })
  wsConnectQueue.length = 0
  wsConnectQueuedTaskIds.clear()
}

const closeSocket = (taskId: string, reason?: 'ws_cooldown' | 'task_polling_terminal' | 'task_inactive' | 'sync_mode_switch' | undefined): void => {
  removeQueuedTaskSocket(taskId)
  wsTaskEpochMap.delete(taskId)
  if (reason) {
    wsExpectedCloseReasonsByTaskId.set(taskId, reason)
  }

  const socket = wsMap.get(taskId)
  if (!socket) return

  logDiag('ws_close_initiated', {
    taskId,
    reason: reason ?? 'unspecified',
    beforeConnections: wsMap.size,
  })

  socket.close()
  wsMap.delete(taskId)
  syncWsConnections()

  logDiag('ws_close_done', {
    taskId,
    afterConnections: wsMap.size,
  })
}

const isTaskCurrentlyActive = (taskId: string): boolean => {
  return tasks.value.some((task) => task.task_id === taskId && ACTIVE_STATUSES.includes(task.status))
}

const patchTaskFromEvent = (
  eventPayload: {
    task_id?: string
    status?: string
    progress?: number
    message?: string
    error?: string | null
  },
  epoch?: number
): void => {
  const taskId = String(eventPayload.task_id ?? '').trim()
  if (!taskId) return

  logDiag('ws_event_received', {
    taskId,
    status: eventPayload.status,
    progress: eventPayload.progress,
    epoch,
    beforeTaskCount: tasks.value.length,
  })

  const next = applyTaskPatchById(
    taskId,
    (current) => ({
      ...current,
      status:
        ACTIVE_STATUSES.includes(String(eventPayload.status ?? '')) ||
        TERMINAL_STATUSES.includes(String(eventPayload.status ?? ''))
          ? (eventPayload.status as QuotationTaskItem['status'])
          : current.status,
      progress: typeof eventPayload.progress === 'number' ? eventPayload.progress : current.progress,
      message: typeof eventPayload.message === 'string' ? eventPayload.message : current.message,
      error: typeof eventPayload.error === 'string' ? eventPayload.error : current.error,
    }),
    {
      epoch,
      source: 'patch_task_from_event',
    }
  )

  if (!next) {
    if (isCurrentEpoch(epoch)) {
      logDiag('ws_event_task_missing', {
        taskId,
        status: eventPayload.status,
        currentTaskCount: tasks.value.length,
      })
    }
    return
  }

  logDiag('ws_event_applied', {
    taskId,
    toStatus: next.status,
    afterTaskCount: tasks.value.length,
  })

  if (TERMINAL_STATUSES.includes(next.status)) {
    approvalDetailRequestedTaskIds.delete(taskId)
    closeSocket(taskId)
  }
}

const connectTaskSocket = (taskId: string): void => {
  const epoch = wsTaskEpochMap.get(taskId)
  if (epoch === undefined || !guardEpoch(epoch, 'ws_connect_guard', { taskId })) {
    removeQueuedTaskSocket(taskId)
    return
  }

  if (isPageUnmounted || !isTaskCurrentlyActive(taskId) || wsMap.has(taskId)) {
    removeQueuedTaskSocket(taskId)
    return
  }

  const wsAttemptId = ++wsConnectAttemptSeq
  const attemptStartedAt = Date.now()
  let firstMessageObserved = false
  logDiagCritical('ws_connect_attempt', {
    wsAttemptId,
    taskId,
    epoch,
    queueLengthBeforeAttempt: wsConnectQueue.length,
    currentConnections: wsMap.size,
    consecutiveFailures: wsConsecutiveFailures,
    visibilityState: document.visibilityState,
    online: getNavigatorOnline(),
    userAgent: getUserAgent(),
  })

  try {
    let socketRef: WebSocket | null = null
    const socket = createTaskWebSocket(taskId, {
      onOpen: (openedSocket) => {
        recordWsHandshakeSuccess(taskId)
        logDiagCritical('ws_open', {
          wsAttemptId,
          taskId,
          epoch,
          elapsedMs: Date.now() - attemptStartedAt,
          queueLengthAfterOpen: wsConnectQueue.length,
          currentConnections: wsMap.size,
          ...describeWebSocket(openedSocket),
        })
      },
      onMessage: (payload, rawEvent) => {
        if (!socketRef || wsMap.get(taskId) !== socketRef) return
        if (!firstMessageObserved) {
          firstMessageObserved = true
          logDiagCritical('ws_first_message', {
            wsAttemptId,
            taskId,
            elapsedMs: Date.now() - attemptStartedAt,
            payloadType: typeof payload,
            dataLength:
              typeof rawEvent.data === 'string'
                ? rawEvent.data.length
                : rawEvent.data instanceof Blob
                  ? rawEvent.data.size
                  : null,
            ...describeWebSocket(socketRef),
          })
        }
        if (!payload || typeof payload !== 'object') return
        const eventPayload = payload as {
          type?: string
          task_id?: string
          event_type?: string
          status?: string
          progress?: number
          message?: string
          error?: string | null
        }
        if (eventPayload.type === 'task_event' && eventPayload.task_id) {
          patchTaskFromEvent(eventPayload, wsTaskEpochMap.get(taskId))
        }
      },
      onError: (event, errorSocket) => {
        if (!socketRef || wsMap.get(taskId) !== socketRef) return
        logDiag('ws_on_error', {
          wsAttemptId,
          taskId,
          currentConnections: wsMap.size,
          elapsedMs: Date.now() - attemptStartedAt,
          eventType: event.type,
          hadFirstMessage: firstMessageObserved,
          ...describeWebSocket(errorSocket),
          visibilityState: document.visibilityState,
          online: getNavigatorOnline(),
        })
        recordWsFailure('ws_on_error', taskId, new Error('ws onerror callback invoked'))
        closeSocket(taskId)
      },
      onClose: (event, closedSocket) => {
        if (!socketRef || wsMap.get(taskId) !== socketRef) return
        const expectedReason = wsExpectedCloseReasonsByTaskId.get(taskId)
        wsExpectedCloseReasonsByTaskId.delete(taskId)
        wsMap.delete(taskId)
        wsTaskEpochMap.delete(taskId)
        syncWsConnections()
        logDiagCritical('ws_on_close', {
          wsAttemptId,
          taskId,
          currentConnections: wsMap.size,
          elapsedMs: Date.now() - attemptStartedAt,
          closeCode: event.code,
          closeReason: event.reason,
          wasClean: event.wasClean,
          expectedCloseReason: expectedReason ?? null,
          hadFirstMessage: firstMessageObserved,
          ...describeWebSocket(closedSocket),
          visibilityState: document.visibilityState,
          online: getNavigatorOnline(),
        })
      },
    })

    socketRef = socket
    wsMap.set(taskId, socket)
    syncWsConnections()

    logDiag('ws_connect_ok', {
      wsAttemptId,
      taskId,
      epoch,
      currentConnections: wsMap.size,
      elapsedMs: Date.now() - attemptStartedAt,
      ...describeWebSocket(socket),
    })
  } catch (error) {
    recordWsFailure('ws_connect_failed', taskId, error)
    logDiagError('ws_connect_failed', error, {
      wsAttemptId,
      taskId,
      epoch,
      currentConnections: wsMap.size,
      elapsedMs: Date.now() - attemptStartedAt,
      visibilityState: document.visibilityState,
      online: getNavigatorOnline(),
      userAgent: getUserAgent(),
    })
    // Ignore websocket startup failures and keep polling fallback.
  }
}

const drainWsConnectQueue = (): void => {
  if (isPageUnmounted) {
    clearWsConnectScheduler()
    return
  }

  if (wsConnectQueue.length > 0) {
    logDiag('ws_queue_drain_start', {
      queueLength: wsConnectQueue.length,
      batchSize: WS_CONNECT_BATCH_SIZE,
      currentConnections: wsMap.size,
    })
  }

  let processed = 0
  while (processed < WS_CONNECT_BATCH_SIZE && wsConnectQueue.length > 0) {
    const taskId = wsConnectQueue.shift()
    if (!taskId) break

    wsConnectQueuedTaskIds.delete(taskId)

    if (!isTaskCurrentlyActive(taskId) || wsMap.has(taskId)) {
      processed += 1
      continue
    }

    connectTaskSocket(taskId)
    processed += 1
  }

  if (wsConnectQueue.length > 0) {
    recordWsQueuePressure('drain_ws_connect_queue_remains')
    wsConnectBatchTimer = window.setTimeout(() => {
      wsConnectBatchTimer = null
      drainWsConnectQueue()
    }, WS_CONNECT_BATCH_INTERVAL_MS)
  }
}

const scheduleWsConnectDrain = (): void => {
  if (wsConnectBatchTimer !== null || wsConnectQueue.length === 0 || isPageUnmounted) return

  wsConnectBatchTimer = window.setTimeout(() => {
    wsConnectBatchTimer = null
    drainWsConnectQueue()
  }, 0)
}

const enqueueTaskSocketConnect = (taskId: string, epoch: number): void => {
  wsTaskEpochMap.set(taskId, epoch)
  if (wsMap.has(taskId) || wsConnectQueuedTaskIds.has(taskId) || isPageUnmounted) return

  wsConnectQueue.push(taskId)
  wsConnectQueuedTaskIds.add(taskId)
  recordWsQueuePressure('enqueue_task_socket_connect')
  scheduleWsConnectDrain()
}

const refreshSingleTask = async (taskId: string, epoch = stateEpoch): Promise<void> => {
  if (refreshInFlightTaskIds.has(taskId)) {
    refreshQueuedTaskIds.add(taskId)
    logDiag('refresh_single_task_deduped', {
      taskId,
      epoch,
      inFlightSize: refreshInFlightTaskIds.size,
      queuedSize: refreshQueuedTaskIds.size,
    })
    return
  }

  refreshInFlightTaskIds.add(taskId)
  logDiag('refresh_single_task_start', {
    taskId,
    epoch,
    inFlightSize: refreshInFlightTaskIds.size,
  })
  try {
    const task = await getQuotationTask(taskId)
    const updated = applyTaskUpsertById(task, {
      epoch,
      source: 'refresh_single_task_success',
    })
    if (updated && ['completed', 'failed', 'cancelled'].includes(updated.status)) {
      stopTaskPolling(taskId)
      closeSocket(taskId)
    }
    logDiag('refresh_single_task_success', {
      taskId,
      epoch,
      status: task.status,
      progress: task.progress,
    })
  } catch (error) {
    logDiagError('refresh_single_task_failed', error, { taskId, epoch })
    // Keep existing task data; detail refresh failures must not trigger a list refresh loop.
  } finally {
    refreshInFlightTaskIds.delete(taskId)
    if (refreshQueuedTaskIds.delete(taskId)) {
      scheduleRefreshSingleTask(taskId, 300, stateEpoch)
    }
    logDiag('refresh_single_task_end', {
      taskId,
      epoch,
      inFlightSize: refreshInFlightTaskIds.size,
      queuedSize: refreshQueuedTaskIds.size,
    })
  }
}

const scheduleRefreshSingleTask = (taskId: string, delay = 500, epoch = stateEpoch): void => {
  const existingTimer = refreshTimers.get(taskId)
  if (existingTimer !== undefined) {
    window.clearTimeout(existingTimer)
  }
  const timer = window.setTimeout(() => {
    refreshTimers.delete(taskId)
    void refreshSingleTask(taskId, epoch)
  }, delay)
  refreshTimers.set(taskId, timer)
}

const ensureTaskSockets = (epoch = stateEpoch): void => {
  if (!ENABLE_TASK_WEBSOCKET) {
    logDiag('ws_disabled_cleanup_start', { existingConnections: wsMap.size })
    clearWsConnectScheduler()
    for (const [taskId] of wsMap) {
      closeSocket(taskId)
    }
    syncWsConnections()
    logDiag('ws_disabled_cleanup_done', { remainingConnections: wsMap.size })
    return
  }

  const nowMs = Date.now()
  const activeTaskIds = new Set(
    tasks.value
      .filter((task) => ACTIVE_STATUSES.includes(task.status))
      .map((task) => task.task_id)
  )

  logDiag('ws_ensure_start', {
    epoch,
    activeTasks: activeTaskIds.size,
    existingConnections: wsMap.size,
    queuedConnections: wsConnectQueue.length,
    maxQueueLengthSeen: wsMaxQueueLengthSeen,
    recentFailuresInWindow: wsFailureTimestamps.length,
    consecutiveFailures: wsConsecutiveFailures,
  })

  for (const existingTaskId of wsMap.keys()) {
    if (!activeTaskIds.has(existingTaskId)) {
      closeSocket(existingTaskId, 'task_inactive')
      continue
    }
    const syncMode = taskSyncModeByTaskId.get(existingTaskId)
    if (syncMode === 'polling') {
      closeSocket(existingTaskId, 'sync_mode_switch')
      continue
    }
    wsTaskEpochMap.set(existingTaskId, epoch)
  }

  for (let i = wsConnectQueue.length - 1; i >= 0; i -= 1) {
    const queuedTaskId = wsConnectQueue[i]
    if (!activeTaskIds.has(queuedTaskId)) {
      wsConnectQueue.splice(i, 1)
      wsConnectQueuedTaskIds.delete(queuedTaskId)
      wsTaskEpochMap.delete(queuedTaskId)
      continue
    }
    if (taskSyncModeByTaskId.get(queuedTaskId) === 'polling') {
      wsConnectQueue.splice(i, 1)
      wsConnectQueuedTaskIds.delete(queuedTaskId)
      wsTaskEpochMap.delete(queuedTaskId)
    }
  }

  activeTaskIds.forEach((taskId) => {
    if (wsMap.has(taskId)) return
    const cooldownUntil = wsDisabledUntilByTaskId.get(taskId)
    if (cooldownUntil !== undefined && nowMs < cooldownUntil) {
      logDiagCritical('ws_connect_suppressed_due_to_cooldown', {
        taskId,
        cooldownUntil,
        remainingMs: cooldownUntil - nowMs,
      })
      if (taskSyncModeByTaskId.get(taskId) !== 'polling') {
        switchTaskSyncMode(taskId, 'polling', 'cooldown_suppress')
      }
      return
    }
    const syncMode = taskSyncModeByTaskId.get(taskId)
    if (syncMode === 'polling') {
      startTaskPolling(taskId)
      return
    }
    enqueueTaskSocketConnect(taskId, epoch)
  })

  recordWsQueuePressure('ensure_task_sockets')
  scheduleWsConnectDrain()

  logDiag('ws_ensure_done', {
    epoch,
    activeTasks: activeTaskIds.size,
    finalConnections: wsMap.size,
    queuedConnections: wsConnectQueue.length,
  })
}

const clearLoadTasksTimeout = (): void => {
  if (loadTasksTimeoutId !== null) {
    window.clearTimeout(loadTasksTimeoutId)
    loadTasksTimeoutId = null
  }
}

const loadTasks = async (options?: { force?: boolean; silent?: boolean }): Promise<void> => {
  const requestId = ++loadTasksRequestSeq
  const mySeq = ++loadTasksActiveSeq
  const startedAt = Date.now()

  if (loading.value) {
    if (!options?.force) {
      loadTasksSkipWhileLoadingCount += 1
      logDiag('load_tasks_skip_due_to_loading', {
        requestId,
        force: false,
        skipCount: loadTasksSkipWhileLoadingCount,
        inFlightRequestId: loadTasksInFlightRequestId,
      })
      return
    }
    loadTasksForceAbortCount += 1
    logDiag('load_tasks_abort_previous', {
      requestId,
      abortReason: 'force_refresh',
      inFlightRequestId: loadTasksInFlightRequestId,
      forceAbortCount: loadTasksForceAbortCount,
    })
    loadTasksAbortController?.abort()
  }

  const requestEpoch = ++stateEpoch

  logDiag('load_tasks_start', {
    requestId,
    requestEpoch,
    force: Boolean(options?.force),
    silent: Boolean(options?.silent),
    loadingBefore: loading.value,
    inFlightRequestIdBeforeStart: loadTasksInFlightRequestId,
    visibilityState: document.visibilityState,
    online: getNavigatorOnline(),
  })

  clearLoadTasksTimeout()
  const controller = new AbortController()
  loadTasksAbortController = controller
  loadTasksInFlightRequestId = requestId
  loadTasksTimeoutId = window.setTimeout(() => {
    logDiag('load_tasks_timeout_abort', {
      requestId,
      requestEpoch,
      abortReason: 'timeout',
      elapsedMs: Date.now() - startedAt,
      inFlightRequestId: loadTasksInFlightRequestId,
    })
    controller.abort()
  }, 15000)

  loading.value = true
  if (!options?.silent) {
    errorMessage.value = ''
  }
  currentRole.value = readUserRole()
  let loadSucceeded = false
  try {
    const fetchStartedAt = Date.now()
    logDiag('load_tasks_fetch_start', {
      requestId,
      requestEpoch,
      limit: 100,
    })
    const response = await listQuotationTasks({
      limit: 100,
      signal: controller.signal,
    })
    const responseReceivedAt = Date.now()
    const fetchMs = responseReceivedAt - fetchStartedAt
    const items = Array.isArray(response.items) ? response.items : []
    const awaitingApprovalCount = items.filter((task) => task.status === 'awaiting_approval').length
    const activeCount = items.filter((task) => ACTIVE_STATUSES.includes(task.status)).length
    const completedCount = items.filter((task) => task.status === 'completed').length
    const responseApproxJsonChars = computeApproxJsonSize(response)
    const responseItemsApproxJsonChars = computeApproxJsonSize(items)

    logDiag('load_tasks_response_received', {
      requestId,
      requestEpoch,
      items: items.length,
      fetchMs,
      elapsedMs: responseReceivedAt - startedAt,
      awaitingApprovalCount,
      activeCount,
      completedCount,
      responseApproxJsonChars,
      responseItemsApproxJsonChars,
    })

    const snapshotApplyStartedAt = Date.now()
    const snapshotApplied = applyTaskListSnapshot(items, {
      epoch: requestEpoch,
      source: 'load_tasks_snapshot_apply',
    })
    const snapshotApplyMs = Date.now() - snapshotApplyStartedAt
    logDiag('load_tasks_snapshot_apply_done', {
      requestId,
      requestEpoch,
      snapshotApplied,
      snapshotApplyMs,
      taskCountAfterApply: tasks.value.length,
    })
    if (!snapshotApplied) {
      return
    }

    const ensureSocketsStartedAt = Date.now()
    ensureTaskSockets(requestEpoch)
    const ensureSocketsMs = Date.now() - ensureSocketsStartedAt
    logDiag('load_tasks_socket_ensure_done', {
      requestId,
      requestEpoch,
      ensureSocketsMs,
      wsConnections: wsMap.size,
      wsQueueLength: wsConnectQueue.length,
    })

    const approvalRefreshScheduleStartedAt = Date.now()
    tasks.value
      .filter((task) =>
        task.status === 'awaiting_approval'
        && !hasApprovalItems(task)
        && !approvalDetailRequestedTaskIds.has(task.task_id)
      )
      .slice(0, 2)
      .forEach((task, index) => {
        approvalDetailRequestedTaskIds.add(task.task_id)
        scheduleRefreshSingleTask(task.task_id, 800 + index * 500, requestEpoch)
      })
    const approvalRefreshScheduleMs = Date.now() - approvalRefreshScheduleStartedAt

    logDiag('load_tasks_success', {
      requestId,
      requestEpoch,
      totalTasksAfterMerge: tasks.value.length,
      fetchMs,
      snapshotApplyMs,
      ensureSocketsMs,
      approvalRefreshScheduleMs,
      elapsedMs: Date.now() - startedAt,
    })
    loadSucceeded = true
    listRefreshSuccessiveFailures = 0
    listRefreshBackoffMultiplier = 1
  } catch (error) {
    listRefreshSuccessiveFailures += 1
    listRefreshBackoffMultiplier = Math.min(listRefreshBackoffMultiplier + 1, 3)
    if (!isCurrentEpoch(requestEpoch)) {
      logDiag('load_tasks_error_ignored_stale_epoch', {
        requestId,
        requestEpoch,
        currentEpoch: stateEpoch,
      })
      return
    }

    if ((error as { name?: string })?.name === 'AbortError') {
      loadTasksAbortErrorCount += 1
      const isTimeout = controller.signal.aborted && loadTasksTimeoutId === null
      const isUnmount = isPageUnmounted
      const abortReason = isUnmount ? 'unmount' : isTimeout ? 'timeout' : 'force_refresh'
      logDiag('load_tasks_abort_error_observed', {
        requestId,
        requestEpoch,
        abortErrorCount: loadTasksAbortErrorCount,
        abortReason,
        signalAborted: controller.signal.aborted,
        elapsedMs: Date.now() - startedAt,
      })
    }

    logDiagError('load_tasks_failed', error, {
      requestId,
      requestEpoch,
      silent: Boolean(options?.silent),
      elapsedMs: Date.now() - startedAt,
      visibilityState: document.visibilityState,
      online: getNavigatorOnline(),
    })
    if (!options?.silent) {
      if ((error as { name?: string })?.name === 'AbortError') {
        errorMessage.value = '加载任务超时，请稍后刷新'
      } else {
        errorMessage.value = (error as { message?: string })?.message ?? '加载任务失败'
      }
    }
  } finally {
    if (loadTasksAbortController === controller) {
      clearLoadTasksTimeout()
      loadTasksAbortController = null
      loading.value = false
      loadTasksInFlightRequestId = null
    }
    logDiag('load_tasks_end', {
      requestId,
      requestEpoch,
      currentEpoch: stateEpoch,
      elapsedMs: Date.now() - startedAt,
      loadingAfter: loading.value,
      taskCount: tasks.value.length,
      inFlightRequestIdAfterEnd: loadTasksInFlightRequestId,
    })

    if (mySeq === loadTasksActiveSeq) {
      scheduleNextListRefresh(loadSucceeded)
    }
  }
}

const computeListRefreshDelayMs = (successiveFailures: number, backoffMultiplier: number): number => {
  if (successiveFailures <= 0) return LIST_REFRESH_NORMAL_MS
  if (backoffMultiplier <= 1) return LIST_REFRESH_BACKOFF_1_MS
  if (backoffMultiplier <= 2) return LIST_REFRESH_BACKOFF_2_MS
  return LIST_REFRESH_BACKOFF_MAX_MS
}

const scheduleNextListRefresh = (justSucceeded: boolean): void => {
  if (isPageUnmounted) return
  if (listRefreshTimerId !== null) {
    window.clearTimeout(listRefreshTimerId)
    listRefreshTimerId = null
  }
  const delayMs = computeListRefreshDelayMs(
    listRefreshSuccessiveFailures,
    listRefreshBackoffMultiplier
  )
  logDiagCritical('list_refresh_backoff_scheduled', {
    delayMs,
    successiveFailures: listRefreshSuccessiveFailures,
    backoffMultiplier: listRefreshBackoffMultiplier,
    justSucceeded,
  })
  listRefreshTimerId = window.setTimeout(() => {
    listRefreshTimerId = null
    void loadTasks({ silent: true })
  }, delayMs)
}

let resumeSyncDebounceTimer: number | null = null

const triggerResumeSync = (trigger: string): void => {
  logDiagCritical('page_resume_sync_triggered', {
    trigger,
    taskCount: tasks.value.length,
    activeCount: tasks.value.filter((t) => ACTIVE_STATUSES.includes(t.status)).length,
    wsConnections: wsMap.size,
  })
  if (resumeSyncDebounceTimer !== null) {
    window.clearTimeout(resumeSyncDebounceTimer)
  }
  resumeSyncDebounceTimer = window.setTimeout(() => {
    resumeSyncDebounceTimer = null
    void loadTasks({ silent: true })
  }, 500)
}

const openFilePicker = (): void => {
  fileInputRef.value?.click()
}

const handleFileSelected = async (event: Event): Promise<void> => {
  const target = event.target as HTMLInputElement
  const selectedFile = target.files?.[0]
  target.value = ''
  const uploadId = ++uploadAttemptSeq
  logDiag('upload_selected', {
    uploadId,
    hasFile: Boolean(selectedFile),
    selectedCount: target.files?.length ?? 0,
    wsMapSizeBeforeUpload: wsMap.size,
    taskCountBeforeUpload: tasks.value.length,
    visibilityState: document.visibilityState,
    online: navigator.onLine,
    loadingAtSelect: loading.value,
    uploadingAtSelect: uploading.value,
  })

  if (!selectedFile) return

  if (selectedFile.type !== 'application/pdf' && !selectedFile.name.toLowerCase().endsWith('.pdf')) {
    logDiag('upload_rejected_invalid_file_type', {
      uploadId,
      fileName: selectedFile.name,
      fileType: selectedFile.type,
    })
    errorMessage.value = '仅支持上传 PDF 文件'
    return
  }

  const defaultTaskName = selectedFile.name.replace(/\.pdf$/i, '') || selectedFile.name
  const customTaskNameInput = window.prompt('请输入任务名称（仅用于展示）', defaultTaskName)
  if (customTaskNameInput === null) {
    logDiag('upload_cancelled_by_prompt', {
      uploadId,
      defaultTaskName,
    })
    return
  }
  const customTaskName = customTaskNameInput.trim() || defaultTaskName

  const uploadStartedAt = Date.now()
  let createTaskStartedAt = 0
  let createTaskPendingWarnTimer: number | null = null

  uploading.value = true
  errorMessage.value = ''
  logDiag('upload_begin', {
    uploadId,
    fileName: selectedFile.name,
    fileType: selectedFile.type,
    fileSize: selectedFile.size,
    taskNameLength: customTaskName.length,
    wsMapSizeAtBegin: wsMap.size,
    taskCountAtBegin: tasks.value.length,
    visibilityState: document.visibilityState,
    online: navigator.onLine,
    loadingAtBegin: loading.value,
  })
  try {
    createTaskStartedAt = Date.now()
    logDiag('upload_before_create_task', {
      uploadId,
      endpoint: '/quotation/tasks',
      visibilityState: document.visibilityState,
      online: navigator.onLine,
      loadingBeforeCreateTask: loading.value,
      wsMapSizeBeforeCreateTask: wsMap.size,
      taskCountBeforeCreateTask: tasks.value.length,
      elapsedFromUploadBeginMs: createTaskStartedAt - uploadStartedAt,
    })

    createTaskPendingWarnTimer = window.setTimeout(() => {
      logDiag('upload_create_task_pending_too_long', {
        uploadId,
        endpoint: '/quotation/tasks',
        elapsedMs: Date.now() - createTaskStartedAt,
        visibilityState: document.visibilityState,
        online: navigator.onLine,
        loadingNow: loading.value,
        wsMapSizeNow: wsMap.size,
        taskCountNow: tasks.value.length,
      })
    }, UPLOAD_CREATE_TASK_PENDING_WARN_MS)

    await createQuotationTask(selectedFile, customTaskName)
    logDiag('upload_after_create_task', {
      uploadId,
      createTaskElapsedMs: Date.now() - createTaskStartedAt,
      totalUploadElapsedMs: Date.now() - uploadStartedAt,
    })
    await loadTasks()
    logDiag('upload_after_load_tasks', {
      uploadId,
      taskCountAfterLoad: tasks.value.length,
      totalUploadElapsedMs: Date.now() - uploadStartedAt,
    })
  } catch (error) {
    logDiagError('upload_failed', error, {
      uploadId,
      fileName: selectedFile.name,
      wsMapSizeOnError: wsMap.size,
      loadingOnError: loading.value,
      onlineOnError: navigator.onLine,
      visibilityStateOnError: document.visibilityState,
      totalUploadElapsedMs: Date.now() - uploadStartedAt,
      createTaskElapsedMs: createTaskStartedAt > 0 ? Date.now() - createTaskStartedAt : null,
    })
    errorMessage.value = (error as { message?: string })?.message ?? '创建任务失败'
  } finally {
    if (createTaskPendingWarnTimer !== null) {
      window.clearTimeout(createTaskPendingWarnTimer)
    }
    uploading.value = false
    logDiag('upload_end', {
      uploadId,
      uploadingAfter: uploading.value,
      errorMessage: errorMessage.value,
      totalUploadElapsedMs: Date.now() - uploadStartedAt,
    })
  }
}

const canCancel = (task: QuotationTaskItem): boolean => {
  return ACTIVE_STATUSES.includes(task.status)
}

const canDelete = (task: QuotationTaskItem): boolean => {
  return TERMINAL_STATUSES.includes(task.status)
}

const handleApprove = async (taskId: string, approvedPartids: string[]): Promise<void> => {
  if (approvingTasks.value.has(taskId)) return
  if (!approvedPartids.length) {
    errorMessage.value = '请至少保留一个已批准的 PARTID'
    return
  }
  approvingTasks.value = new Set([...approvingTasks.value, taskId])
  try {
    await approveQuotationTask(taskId, approvedPartids)
    await refreshSingleTask(taskId)
  } catch (error) {
    errorMessage.value = (error as { message?: string })?.message ?? '提交审核同意失败'
  } finally {
    const next = new Set(approvingTasks.value)
    next.delete(taskId)
    approvingTasks.value = next
  }
}

const handleCancel = async (taskId: string): Promise<void> => {
  try {
    await cancelQuotationTask(taskId)
    await refreshSingleTask(taskId)
  } catch (error) {
    errorMessage.value = (error as { message?: string })?.message ?? '取消任务失败'
  }
}

const handleDelete = async (taskId: string): Promise<void> => {
  const task = tasks.value.find((item) => item.task_id === taskId)
  const taskName = task?.display_name || task?.uploaded_file_name || taskId
  const confirmed = window.confirm(`确定删除任务「${taskName}」吗？此操作不可恢复。`)
  if (!confirmed) return

  try {
    await deleteQuotationTask(taskId)
    closeSocket(taskId)
    approvalDetailRequestedTaskIds.delete(taskId)
    refreshInFlightTaskIds.delete(taskId)
    refreshQueuedTaskIds.delete(taskId)

    const timer = refreshTimers.get(taskId)
    if (timer !== undefined) {
      window.clearTimeout(timer)
      refreshTimers.delete(taskId)
    }

    const deletingSelectedTask = selectedTask.value?.task_id === taskId
    tasks.value = tasks.value.filter((item) => item.task_id !== taskId)
    syncSelectedTaskRef()
    if (deletingSelectedTask) {
      selectedTask.value = null
      resultModalVisible.value = false
    }
  } catch (error) {
    errorMessage.value = (error as { message?: string })?.message ?? '删除任务失败'
  }
}

const openResultModal = (task: QuotationTaskItem): void => {
  logPhase2ResultSnapshot(task, 'open_result_modal')
  selectedTask.value = task
  resultModalVisible.value = true
}

const closeResultModal = (): void => {
  resultModalVisible.value = false
}

const handleViewFile = async (taskId: string): Promise<void> => {
  try {
    const { blob, filename } = await downloadQuotationTaskFile(taskId)
    const url = URL.createObjectURL(blob)
    const openWindow = window.open(url, '_blank')
    if (!openWindow) {
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    }
    window.setTimeout(() => URL.revokeObjectURL(url), 2000)
  } catch (error) {
    errorMessage.value = (error as { message?: string })?.message ?? '查看文件失败'
  }
}

const handleDownloadU8Xlsx = async (taskId: string): Promise<void> => {
  try {
    const { blob, filename } = await downloadQuotationU8ByTypeWorkbook(taskId)
    const url = URL.createObjectURL(blob)
    const openWindow = window.open(url, '_blank')
    if (!openWindow) {
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
    }
    window.setTimeout(() => URL.revokeObjectURL(url), 2000)
  } catch (error) {
    errorMessage.value = (error as { message?: string })?.message ?? '下载 U8 分组 Excel 失败'
  }
}

onMounted(() => {
  isPageUnmounted = false
  window.addEventListener('error', handleWindowError)
  window.addEventListener('unhandledrejection', handleUnhandledRejection)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  window.addEventListener('online', handleOnline)
  window.addEventListener('offline', handleOffline)
  window.addEventListener('focus', handleFocus)
  window.addEventListener('blur', handleBlur)
  startEventLoopLagProbe()
  logPageEnvironment('page_mounted', {
    userRole: currentRole.value,
  })

  void loadTasks()
})

onUnmounted(() => {
  isPageUnmounted = true
  window.removeEventListener('error', handleWindowError)
  window.removeEventListener('unhandledrejection', handleUnhandledRejection)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  window.removeEventListener('online', handleOnline)
  window.removeEventListener('offline', handleOffline)
  window.removeEventListener('focus', handleFocus)
  window.removeEventListener('blur', handleBlur)
  stopEventLoopLagProbe()
  logPageEnvironment('page_unmounted_start', {
    connectionsBeforeCleanup: wsMap.size,
  })

  if (listRefreshTimerId !== null) {
    window.clearTimeout(listRefreshTimerId)
    listRefreshTimerId = null
  }
  loadTasksAbortController?.abort()
  clearLoadTasksTimeout()
  clearWsConnectScheduler()
  if (resumeSyncDebounceTimer !== null) {
    window.clearTimeout(resumeSyncDebounceTimer)
    resumeSyncDebounceTimer = null
  }
  for (const timer of refreshTimers.values()) {
    window.clearTimeout(timer)
  }
  refreshTimers.clear()
  for (const timer of taskPollingTimerByTaskId.values()) {
    window.clearTimeout(timer)
  }
  taskPollingTimerByTaskId.clear()
  for (const [taskId] of wsMap) {
    closeSocket(taskId)
  }

  logPageEnvironment('page_unmounted_done', {
    connectionsAfterCleanup: wsMap.size,
  })
})

const TaskItemCard = defineComponent({
  name: 'TaskItemCard',
  props: {
    task: {
      type: Object as () => QuotationTaskItem,
      required: true,
    },
    showOwner: {
      type: Boolean,
      required: true,
    },
    canCancel: {
      type: Boolean,
      required: true,
    },
    canDelete: {
      type: Boolean,
      required: true,
    },
    isApproving: {
      type: Boolean,
      default: false,
    },
  },
  emits: ['cancel', 'delete', 'approve', 'view-result', 'view-file', 'download-u8-xlsx'],
  setup(props, { emit }) {
    const RING_RADIUS = 20
    const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS
    const progress = computed(() => Math.max(0, Math.min(100, props.task.progress ?? 0)))
    const ringDashOffset = computed(() => RING_CIRCUMFERENCE * (1 - progress.value / 100))
    const statusText = computed(() => {
      if (props.task.status === 'queued') return '排队中'
      if (props.task.status === 'running') return '处理中'
      if (props.task.status === 'awaiting_approval') return '等待审核'
      if (props.task.status === 'completed') return '已完成'
      if (props.task.status === 'failed') return '失败'
      return '已取消'
    })
    const progressStrokeClass = computed(() => {
      if (props.task.status === 'queued') return 'task-progress-ring__value--queued'
      if (props.task.status === 'running') return 'task-progress-ring__value--running'
      if (props.task.status === 'awaiting_approval') return 'task-progress-ring__value--awaiting'
      if (props.task.status === 'completed') return 'task-progress-ring__value--completed'
      if (props.task.status === 'failed') return 'task-progress-ring__value--failed'
      return 'task-progress-ring__value--cancelled'
    })

    const pdmItems = computed<QuotationPdmItem[]>(() => {
      const result = props.task.result as { pdm_result?: QuotationPdmResult } | null | undefined
      const items = result?.pdm_result?.items
      return Array.isArray(items) ? items : []
    })

    let lastPhase2UiSnapshotAt = 0
    let lastApprovalGroupComputeLogAt = 0
    let lastPdmRenderCostLogAt = 0

    interface PdmApprovalRow {
      key: string
      partid: string
      chinaname: string
      typeName: string
      raw: QuotationPdmItem
    }

    interface PdmApprovalGroup {
      key: string
      typeName: string
      rows: PdmApprovalRow[]
    }

    const parseQueryIndex = (value: unknown): number | null => {
      if (typeof value === 'number' && Number.isFinite(value)) return Math.trunc(value)
      if (typeof value === 'string') {
        const parsed = Number.parseInt(value.trim(), 10)
        return Number.isFinite(parsed) ? parsed : null
      }
      return null
    }

    const makeRowKey = (groupKey: string, chinaname: string, partid: string): string =>
      `${groupKey}\u0000${chinaname}\u0000${partid}`

    const keywordTypeByIndex = computed<Map<number, string>>(() => {
      const map = new Map<number, string>()
      const result = props.task.result as
        | {
            keywords_payload?: {
              keywords?: unknown
            }
          }
        | null
        | undefined
      const keywords = result?.keywords_payload?.keywords
      if (!Array.isArray(keywords)) return map

      keywords.forEach((entry, idx) => {
        if (!entry || typeof entry !== 'object') return
        const typeName = String((entry as Record<string, unknown>).type ?? '').trim()
        if (!typeName) return
        map.set(idx, typeName)
      })

      return map
    })

    const resolveTypeName = (item: QuotationPdmItem): string => {
      const queryIndex = parseQueryIndex(item?.QUERY_INDEX)
      // PDM API sets QUERY_INDEX with enumerate(keyword_groups, start=1) — map keywords_payload by (index - 1).
      if (queryIndex !== null) {
        const typeFromOneBasedPdm = keywordTypeByIndex.value.get(queryIndex - 1)
        if (typeFromOneBasedPdm) return typeFromOneBasedPdm
        const typeFromZeroBasedIndex = keywordTypeByIndex.value.get(queryIndex)
        if (typeFromZeroBasedIndex) return typeFromZeroBasedIndex
      }

      const fallbackKeywords = item?.QUERY_KEYWORDS
      if (Array.isArray(fallbackKeywords)) {
        const firstKeyword = fallbackKeywords.find(
          (keyword) => String(keyword ?? '').trim().length > 0
        )
        if (firstKeyword !== undefined && firstKeyword !== null) {
          const text = String(firstKeyword).trim()
          if (text) return text
        }
      }

      return '未分组'
    }

    const approvalGroups = computed<PdmApprovalGroup[]>(() => {
      const startedAt = performance.now()
      const orderedGroups: PdmApprovalGroup[] = []
      const groupMap = new Map<string, { group: PdmApprovalGroup; seenRowKeys: Set<string> }>()

      for (const item of pdmItems.value) {
        const rawPartid = item?.PARTID
        if (rawPartid === undefined || rawPartid === null) continue
        const partid = String(rawPartid).trim()
        if (!partid) continue

        const chinaname =
          item?.CHINANAME === undefined || item?.CHINANAME === null
            ? ''
            : String(item.CHINANAME).trim()

        const typeName = resolveTypeName(item)
        const groupKey = typeName

        if (!groupMap.has(groupKey)) {
          const group: PdmApprovalGroup = {
            key: groupKey,
            typeName,
            rows: [],
          }
          groupMap.set(groupKey, { group, seenRowKeys: new Set<string>() })
          orderedGroups.push(group)
        }

        const hit = groupMap.get(groupKey)
        if (!hit) continue
        const innerDedupKey = `${chinaname}\u0000${partid}`
        if (hit.seenRowKeys.has(innerDedupKey)) continue
        hit.seenRowKeys.add(innerDedupKey)

        hit.group.rows.push({
          key: makeRowKey(groupKey, chinaname, partid),
          partid,
          chinaname,
          typeName,
          raw: item,
        })
      }

      const elapsedMs = performance.now() - startedAt
      const nowMs = Date.now()
      if (elapsedMs >= 30 || nowMs - lastApprovalGroupComputeLogAt >= 5000) {
        lastApprovalGroupComputeLogAt = nowMs
        logDiag('phase2_approval_groups_compute_cost', {
          taskId: props.task.task_id,
          taskStatus: props.task.status,
          pdmItemCount: pdmItems.value.length,
          groupCount: orderedGroups.length,
          elapsedMs,
        })
      }

      return orderedGroups
    })

    const allApprovalRows = computed<PdmApprovalRow[]>(() =>
      approvalGroups.value.flatMap((group) => group.rows)
    )

    watch(
      [approvalGroups, allApprovalRows, keywordTypeByIndex],
      ([groups, rows, keywordTypeMap]) => {
        const nowMs = Date.now()
        if (nowMs - lastPhase2UiSnapshotAt < 1500) return
        lastPhase2UiSnapshotAt = nowMs

        logDiag('phase2_ui_snapshot', {
          taskId: props.task.task_id,
          taskStatus: props.task.status,
          pdmItemCount: pdmItems.value.length,
          groupCount: groups.length,
          rowCount: rows.length,
          keywordTypeCount: keywordTypeMap.size,
          resultApproxJsonChars: computeApproxJsonSize(props.task.result),
        })
      },
      { immediate: true }
    )

    const approvedRowKeys = ref<Set<string>>(new Set())
    const expandedGroupKeys = ref<Set<string>>(new Set())

    watch(
      allApprovalRows,
      (next, prev) => {
        const prevKeys = new Set((prev ?? []).map((row) => row.key))
        const nextKeys = new Set(next.map((row) => row.key))
        const updated = new Set<string>()
        for (const key of approvedRowKeys.value) {
          if (nextKeys.has(key)) updated.add(key)
        }
        for (const row of next) {
          if (!prevKeys.has(row.key)) updated.add(row.key)
        }
        approvedRowKeys.value = updated
      },
      { immediate: true }
    )

    watch(
      approvalGroups,
      (next, prev) => {
        const nextKeys = new Set(next.map((group) => group.key))
        const updated = new Set<string>()
        for (const key of expandedGroupKeys.value) {
          if (nextKeys.has(key)) updated.add(key)
        }

        const hadPrev = Array.isArray(prev) && prev.length > 0
        if (!hadPrev && next.length > 0 && updated.size === 0) {
          updated.add(next[0].key)
        }

        expandedGroupKeys.value = updated
      },
      { immediate: true }
    )

    const approvedCount = computed(() => approvedRowKeys.value.size)
    const allSelected = computed(
      () => allApprovalRows.value.length > 0 && approvedCount.value === allApprovalRows.value.length
    )
    const noneSelected = computed(() => approvedCount.value === 0)

    const approvedPartidsPreview = computed<string[]>(() => {
      const seen = new Set<string>()
      const ordered: string[] = []
      for (const row of allApprovalRows.value) {
        if (!approvedRowKeys.value.has(row.key)) continue
        if (seen.has(row.partid)) continue
        seen.add(row.partid)
        ordered.push(row.partid)
      }
      return ordered
    })

    const isGroupExpanded = (groupKey: string): boolean => expandedGroupKeys.value.has(groupKey)

    const toggleGroupExpanded = (groupKey: string): void => {
      const next = new Set(expandedGroupKeys.value)
      if (next.has(groupKey)) next.delete(groupKey)
      else next.add(groupKey)
      expandedGroupKeys.value = next
    }

    const allExpanded = computed(
      () =>
        approvalGroups.value.length > 0 &&
        approvalGroups.value.every((group) => expandedGroupKeys.value.has(group.key))
    )

    const toggleExpandAll = (): void => {
      if (allExpanded.value) {
        expandedGroupKeys.value = new Set()
      } else {
        expandedGroupKeys.value = new Set(approvalGroups.value.map((group) => group.key))
      }
    }

    const toggleRow = (rowKey: string): void => {
      const next = new Set(approvedRowKeys.value)
      if (next.has(rowKey)) next.delete(rowKey)
      else next.add(rowKey)
      approvedRowKeys.value = next
    }

    const toggleAll = (): void => {
      if (allSelected.value) {
        approvedRowKeys.value = new Set()
      } else {
        approvedRowKeys.value = new Set(allApprovalRows.value.map((row) => row.key))
      }
    }

    const getGroupSelectedCount = (group: PdmApprovalGroup): number => {
      let count = 0
      for (const row of group.rows) {
        if (approvedRowKeys.value.has(row.key)) count += 1
      }
      return count
    }

    const getGroupApprovedPartidCount = (group: PdmApprovalGroup): number => {
      const seen = new Set<string>()
      for (const row of group.rows) {
        if (!approvedRowKeys.value.has(row.key)) continue
        seen.add(row.partid)
      }
      return seen.size
    }

    const isGroupAllSelected = (group: PdmApprovalGroup): boolean =>
      group.rows.length > 0 && getGroupSelectedCount(group) === group.rows.length

    const isGroupNoneSelected = (group: PdmApprovalGroup): boolean => getGroupSelectedCount(group) === 0

    const toggleGroupSelection = (group: PdmApprovalGroup): void => {
      const next = new Set(approvedRowKeys.value)
      if (isGroupAllSelected(group)) {
        for (const row of group.rows) {
          next.delete(row.key)
        }
      } else {
        for (const row of group.rows) {
          next.add(row.key)
        }
      }
      approvedRowKeys.value = next
    }

    const submitApproval = (): void => {
      emit('approve', [...approvedPartidsPreview.value])
    }

    const formatList = (value: unknown): string => {
      if (Array.isArray(value)) return value.join(' / ')
      if (value === undefined || value === null) return ''
      return String(value)
    }

    const renderPdmGroupTable = (group: PdmApprovalGroup) => {
      if (!isGroupExpanded(group.key)) return null

      return h('div', { class: 'pdm-approval-group__table-wrapper' }, [
        h('table', { class: 'pdm-approval__table' }, [
          h('thead', null, [
            h('tr', null, [
              h('th', { key: '__checkbox', class: 'pdm-approval__checkbox-col' }),
              h('th', { key: 'CHINANAME' }, '名称'),
              h('th', { key: 'PARTID' }, 'PARTID'),
              h('th', { key: 'QUERY_KEYWORDS' }, '关键词'),
              h('th', { key: 'QUERY_EXPANDED_KEYWORDS' }, '扩展关键词'),
            ]),
          ]),
          h(
            'tbody',
            null,
            group.rows.map((row) => {
              const isChecked = approvedRowKeys.value.has(row.key)
              const queryKeywordsText = formatList(row.raw?.QUERY_KEYWORDS)
              const queryExpandedKeywordsText = formatList(row.raw?.QUERY_EXPANDED_KEYWORDS)

              return h(
                'tr',
                {
                  key: row.key,
                  class: !isChecked ? 'pdm-approval__row--skipped' : undefined,
                },
                [
                  h('td', { key: '__checkbox', class: 'pdm-approval__checkbox-col' }, [
                    h('input', {
                      type: 'checkbox',
                      class: 'pdm-approval__checkbox',
                      checked: isChecked,
                      disabled: props.isApproving,
                      'aria-label': `批准 ${row.chinaname || '(无名称)'} / ${row.partid}`,
                      onChange: () => toggleRow(row.key),
                    }),
                  ]),
                  h('td', { key: 'CHINANAME', title: row.chinaname }, row.chinaname),
                  h('td', { key: 'PARTID', title: row.partid }, row.partid),
                  h('td', { key: 'QUERY_KEYWORDS', title: queryKeywordsText }, queryKeywordsText),
                  h(
                    'td',
                    { key: 'QUERY_EXPANDED_KEYWORDS', title: queryExpandedKeywordsText },
                    queryExpandedKeywordsText
                  ),
                ]
              )
            })
          ),
        ]),
      ])
    }

    const renderPdmTable = () => {
      if (props.task.status !== 'awaiting_approval') return null
      const renderStartedAt = performance.now()
      const items = pdmItems.value
      if (items.length === 0) {
        const emptyNode = h('div', { class: 'pdm-approval' }, [h('p', { class: 'pdm-approval__empty' }, 'PDM 未返回任何数据')])
        const elapsedMs = performance.now() - renderStartedAt
        if (elapsedMs >= 20) {
          logDiag('phase2_render_pdm_table_cost', {
            taskId: props.task.task_id,
            taskStatus: props.task.status,
            pdmItemCount: items.length,
            groupCount: 0,
            rowCount: 0,
            elapsedMs,
            isEmpty: true,
          })
        }
        return emptyNode
      }

      const groups = approvalGroups.value
      const rowCount = allApprovalRows.value.length
      const partidCount = approvedPartidsPreview.value.length

      const node = h('div', { class: 'pdm-approval' }, [
        h(
          'p',
          { class: 'pdm-approval__title' },
          `PDM 候选审核（按 type 折叠，${groups.length} 组） · 共 ${items.length} 条，已批准 ${approvedCount.value}/${rowCount} 行，将提交 ${partidCount} 个 PARTID`
        ),
        h('div', { class: 'pdm-approval__toolbar' }, [
          h('label', { class: 'pdm-approval__toolbar-main' }, [
            h('input', {
              type: 'checkbox',
              class: 'pdm-approval__checkbox',
              checked: allSelected.value,
              indeterminate: !allSelected.value && !noneSelected.value,
              disabled: props.isApproving || rowCount === 0,
              'aria-label': '全选/全不选',
              onChange: toggleAll,
            }),
            h('span', null, `全选候选（${approvedCount.value}/${rowCount}）`),
          ]),
          h(
            'button',
            {
              type: 'button',
              class: 'pdm-approval__ghost-btn',
              disabled: props.isApproving || groups.length === 0,
              onClick: toggleExpandAll,
            },
            allExpanded.value ? '全部收起' : '全部展开'
          ),
        ]),
        h(
          'div',
          { class: 'pdm-approval__groups' },
          groups.map((group) => {
            const isExpanded = isGroupExpanded(group.key)
            const groupSelectedCount = getGroupSelectedCount(group)
            const groupPartidCount = getGroupApprovedPartidCount(group)
            const groupAllSelected = isGroupAllSelected(group)
            const groupNoneSelected = isGroupNoneSelected(group)

            return h('section', { key: group.key, class: 'pdm-approval-group' }, [
              h('div', { class: 'pdm-approval-group__header' }, [
                h(
                  'button',
                  {
                    type: 'button',
                    class: 'pdm-approval-group__toggle',
                    onClick: () => toggleGroupExpanded(group.key),
                  },
                  [
                    h('span', { class: 'pdm-approval-group__chevron', 'aria-hidden': 'true' }, isExpanded ? '▾' : '▸'),
                    h('span', { class: 'pdm-approval-group__type', title: group.typeName }, group.typeName),
                    h(
                      'span',
                      { class: 'pdm-approval-group__meta' },
                      `已选 ${groupSelectedCount}/${group.rows.length} · 提交 ${groupPartidCount} PARTID`
                    ),
                  ]
                ),
                h('label', { class: 'pdm-approval-group__pickall' }, [
                  h('input', {
                    type: 'checkbox',
                    class: 'pdm-approval__checkbox',
                    checked: groupAllSelected,
                    indeterminate: !groupAllSelected && !groupNoneSelected,
                    disabled: props.isApproving || group.rows.length === 0,
                    'aria-label': `全选 ${group.typeName} 候选`,
                    onChange: () => toggleGroupSelection(group),
                  }),
                  h('span', null, '本组全选'),
                ]),
              ]),
              renderPdmGroupTable(group),
            ])
          })
        ),
        h(
          'button',
          {
            class: 'task-action-btn task-action-btn--accent pdm-approval__approve',
            disabled: props.isApproving || noneSelected.value,
            onClick: submitApproval,
          },
          props.isApproving
            ? '提交中...'
            : `提交已批准项（${partidCount} 个 PARTID）并继续 U8 查询`
        ),
      ])

      const elapsedMs = performance.now() - renderStartedAt
      const nowMs = Date.now()
      if (elapsedMs >= 25 || nowMs - lastPdmRenderCostLogAt >= 5000) {
        lastPdmRenderCostLogAt = nowMs
        logDiag('phase2_render_pdm_table_cost', {
          taskId: props.task.task_id,
          taskStatus: props.task.status,
          pdmItemCount: items.length,
          groupCount: groups.length,
          rowCount,
          approvedCount: approvedCount.value,
          elapsedMs,
          isEmpty: false,
        })
      }

      return node
    }
    const progressMessage = computed(() => {
      const raw = String(props.task.message ?? '').trim()
      if (!raw || raw === statusText.value) {
        return ''
      }
      return raw
    })
    const shortTaskId = computed(() => {
      const raw = String(props.task.task_id ?? '').trim()
      if (!raw) return '--'
      return `#${raw.slice(-8)}`
    })

    const formatTime = (value: string): string => {
      const date = new Date(value)
      if (Number.isNaN(date.getTime())) {
        return value
      }
      return date.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
    }

    const hasU8ByTypeWorkbook = computed(() => {
      return props.task.status === 'completed'
    })

    return () =>
      h('article', { class: 'task-card' }, [
        h('div', { class: 'task-card__title' }, props.task.display_name || props.task.uploaded_file_name),
        h('div', { class: 'task-card__meta' }, [h('span', { class: ['status', `status--${props.task.status}`] }, statusText.value)]),
        h('div', { class: 'task-card__progress' }, [
          h(
            'div',
            {
              class: 'task-progress-ring',
              role: 'progressbar',
              'aria-label': `任务进度 ${progress.value}%`,
              'aria-valuemin': 0,
              'aria-valuemax': 100,
              'aria-valuenow': progress.value,
            },
            [
              h('svg', { class: 'task-progress-ring__svg', viewBox: '0 0 48 48', 'aria-hidden': 'true' }, [
                h('circle', { class: 'task-progress-ring__track', cx: 24, cy: 24, r: RING_RADIUS }),
                h('circle', {
                  class: ['task-progress-ring__value', progressStrokeClass.value],
                  cx: 24,
                  cy: 24,
                  r: RING_RADIUS,
                  'stroke-dasharray': RING_CIRCUMFERENCE.toFixed(2),
                  'stroke-dashoffset': ringDashOffset.value.toFixed(2),
                }),
              ]),
              h('span', { class: 'task-progress-ring__label' }, `${progress.value}%`),
            ]
          ),
          h('div', { class: 'task-card__progress-copy' }, [
            h('p', { class: 'task-card__progress-percent' }, `${progress.value}%`),
            h('p', { class: 'task-card__progress-caption' }, `当前状态：${statusText.value}`),
          ]),
        ]),
        progressMessage.value ? h('p', { class: 'task-card__progress-text' }, progressMessage.value) : null,
        renderPdmTable(),
        h('div', { class: 'task-card__footnote' }, [
          props.showOwner ? h('span', { class: 'task-card__owner', title: props.task.owner_username }, props.task.owner_username) : null,
          h('span', { class: 'task-card__id', title: props.task.task_id }, shortTaskId.value),
          h('span', { class: 'task-card__time' }, formatTime(props.task.created_at)),
        ]),
        props.task.error ? h('p', { class: 'task-card__error' }, props.task.error) : null,
        h('div', { class: 'task-card__actions' }, [
          h(
            'button',
            { class: 'task-action-btn task-action-btn--danger', disabled: !props.canCancel, onClick: () => emit('cancel') },
            '中断'
          ),
          h('button', { class: 'task-action-btn task-action-btn--neutral', onClick: () => emit('view-result') }, '结果'),
          h('button', { class: 'task-action-btn task-action-btn--accent', onClick: () => emit('view-file') }, '文件'),
          hasU8ByTypeWorkbook.value
            ? h(
                'button',
                {
                  class: 'task-action-btn task-action-btn--accent',
                  onClick: () => emit('download-u8-xlsx'),
                },
                '下载Excel'
              )
            : null,
          props.canDelete
            ? h(
                'button',
                { class: 'task-action-btn task-action-btn--danger', onClick: () => emit('delete') },
                '删除'
              )
            : null,
        ]),
      ])
  },
})
</script>

<style scoped lang="scss">
.quotation-page {
  height: 100%;
  padding: 24px 24px 16px;
  overflow: auto;
  box-sizing: border-box;
  background: var(--yamato-color-bg-light);
}

.hidden-input {
  display: none;
}

.quotation-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.quotation-title {
  margin: 0;
  color: var(--yamato-color-text-primary);
  font-family: var(--yamato-font-display);
  font-size: 34px;
  font-weight: 500;
  line-height: 1.2;
  letter-spacing: 0;
}

.quotation-subtitle {
  margin: 6px 0 0;
  color: var(--yamato-color-text-secondary);
  font-size: 14px;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.primary-btn,
.secondary-btn {
  min-height: 36px;
  padding: 0 14px;
  cursor: pointer;
  font-size: 14px;
  border-radius: var(--yamato-radius-md);
  transition: background 0.2s ease, color 0.2s ease, box-shadow 0.2s ease;

  &:focus-visible {
    outline: none;
    box-shadow: var(--yamato-focus-ring);
  }
}

.primary-btn {
  border: none;
  background: var(--yamato-color-accent);
  color: #fff;

  &:hover:not(:disabled) {
    background: var(--yamato-color-accent-hover);
  }
}

.secondary-btn {
  border: 1px solid var(--yamato-color-border-subtle);
  background: var(--yamato-color-surface);
  color: var(--yamato-color-text-primary);

  &:hover:not(:disabled) {
    background: var(--yamato-color-surface-alt);
  }
}

.primary-btn:disabled,
.secondary-btn:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.error-tip {
  margin: 0 0 12px;
  color: var(--yamato-color-danger);
}

.columns {
  display: grid;
  /* Slightly narrow queue column; give space to in-progress (处理中) column; done column share unchanged */
  grid-template-columns: minmax(220px, 0.6fr) minmax(260px, 1.4fr) minmax(220px, 1fr);
  gap: 14px;
  min-height: 0;
}

.column {
  background: #ffffff;
  border-radius: var(--yamato-radius-lg);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 420px;
  box-shadow: var(--yamato-shadow-card);
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}

.column--done .task-list--scroll {
  max-height: clamp(260px, calc(100vh - 320px), 640px);
  overflow-y: auto;
  padding-right: 4px;
}

.column-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.column-header h2 {
  margin: 0;
  font-size: 21px;
  line-height: 1.19;
  letter-spacing: -0.22px;
  color: var(--yamato-color-text-primary);
}

.column-header span {
  color: var(--yamato-color-text-muted);
  font-size: 13px;
}

.dev-tip {
  margin: 0;
  color: var(--yamato-color-warning);
  background: var(--yamato-color-warning-soft);
  padding: 8px;
  border-radius: var(--yamato-radius-sm);
  font-size: 12px;
}

.empty {
  color: var(--yamato-color-text-muted);
  font-size: 13px;
  margin-top: 6px;
}

:deep(.task-card) {
  border-radius: var(--yamato-radius-sm);
  padding: 10px 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 7px;
  background: var(--yamato-color-surface-alt);
}

:deep(.task-card__title) {
  font-weight: 600;
  font-size: 14px;
  color: var(--yamato-color-text-primary);
  word-break: break-all;
}

:deep(.task-card__owner),
:deep(.task-card__time),
:deep(.task-card__progress-text),
:deep(.task-card__id) {
  margin: 0;
  color: var(--yamato-color-text-secondary);
  font-size: 12px;
  line-height: 1.4;
}

:deep(.task-card__meta) {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

:deep(.task-card__progress) {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  border-radius: var(--yamato-radius-sm);
  border: 1px solid var(--yamato-color-border-subtle);
  background: #ffffff;
}

:deep(.task-progress-ring) {
  position: relative;
  width: 58px;
  height: 58px;
  flex: 0 0 58px;
}

:deep(.task-progress-ring__svg) {
  width: 58px;
  height: 58px;
}

:deep(.task-progress-ring__track),
:deep(.task-progress-ring__value) {
  fill: none;
  stroke-width: 5;
}

:deep(.task-progress-ring__track) {
  stroke: #e8e6dc;
}

:deep(.task-progress-ring__value) {
  stroke-linecap: round;
  transform: rotate(-90deg);
  transform-origin: 50% 50%;
  transition: stroke-dashoffset 0.28s ease, stroke 0.28s ease;
}

:deep(.task-progress-ring__value--queued) {
  stroke: var(--yamato-color-warning);
}

:deep(.task-progress-ring__value--running) {
  stroke: var(--yamato-color-accent);
}

:deep(.task-progress-ring__value--awaiting) {
  stroke: var(--yamato-color-warning);
}

:deep(.task-progress-ring__value--completed) {
  stroke: var(--yamato-color-success);
}

:deep(.task-progress-ring__value--failed),
:deep(.task-progress-ring__value--cancelled) {
  stroke: var(--yamato-color-danger);
}

:deep(.task-progress-ring__label) {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  color: var(--yamato-color-text-primary);
}

:deep(.task-card__progress-copy) {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

:deep(.task-card__progress-percent) {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--yamato-color-text-primary);
}

:deep(.task-card__progress-caption) {
  margin: 0;
  font-size: 12px;
  color: var(--yamato-color-text-secondary);
  line-height: 1.4;
}

:deep(.status) {
  font-size: 12px;
  font-weight: 600;
}

:deep(.status--queued) {
  color: var(--yamato-color-warning);
}

:deep(.status--running) {
  color: var(--yamato-color-accent);
}

:deep(.status--awaiting_approval) {
  color: var(--yamato-color-warning);
}

:deep(.status--completed) {
  color: var(--yamato-color-success);
}

:deep(.status--failed),
:deep(.status--cancelled) {
  color: var(--yamato-color-danger);
}

:deep(.task-card__error) {
  margin: 0;
  color: var(--yamato-color-danger);
  font-size: 12px;
}

:deep(.task-card__footnote) {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--yamato-color-text-muted);
  min-width: 0;
}

:deep(.task-card__footnote .task-card__owner),
:deep(.task-card__footnote .task-card__id),
:deep(.task-card__footnote .task-card__time) {
  white-space: nowrap;
}

:deep(.task-card__footnote .task-card__owner) {
  max-width: 86px;
  overflow: hidden;
  text-overflow: ellipsis;
}

:deep(.task-card__footnote .task-card__id) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
}

:deep(.pdm-approval) {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border-radius: 12px;
  border: 1px solid #f0eee6;
  background: #faf9f5;
  box-shadow: 0 0 0 1px #f0eee6;
}

:deep(.pdm-approval__title) {
  margin: 0;
  color: #141413;
  font-family: var(--yamato-font-display), Georgia, serif;
  font-size: 16px;
  font-weight: 500;
  line-height: 1.25;
}

:deep(.pdm-approval__empty) {
  margin: 0;
  font-size: 12px;
  color: #87867f;
}

:deep(.pdm-approval__toolbar) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

:deep(.pdm-approval__toolbar-main) {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: #4d4c48;
  font-size: 12px;
  line-height: 1.4;
}

:deep(.pdm-approval__ghost-btn) {
  height: 28px;
  padding: 0 10px;
  border: 1px solid #d1cfc5;
  border-radius: 8px;
  background: #e8e6dc;
  color: #4d4c48;
  font-size: 12px;
  cursor: pointer;
  box-shadow: 0 0 0 1px #d1cfc5;

  &:hover:not(:disabled) {
    background: #f0eee6;
  }

  &:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
}

:deep(.pdm-approval__groups) {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

:deep(.pdm-approval-group) {
  border: 1px solid #e8e6dc;
  border-radius: 10px;
  background: #ffffff;
  overflow: hidden;
}

:deep(.pdm-approval-group__header) {
  min-height: 40px;
  background: #faf9f5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border-bottom: 1px solid #f0eee6;
}

:deep(.pdm-approval-group__toggle) {
  flex: 1;
  min-width: 0;
  border: none;
  background: transparent;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0;
  text-align: left;
  cursor: pointer;

  &:hover {
    opacity: 0.86;
  }
}

:deep(.pdm-approval-group__chevron) {
  color: #5e5d59;
  font-size: 12px;
}

:deep(.pdm-approval-group__type) {
  color: #141413;
  font-family: var(--yamato-font-display), Georgia, serif;
  font-size: 15px;
  font-weight: 500;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:deep(.pdm-approval-group__meta) {
  color: #5e5d59;
  font-size: 12px;
  white-space: nowrap;
}

:deep(.pdm-approval-group__pickall) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #4d4c48;
  font-size: 12px;
}

:deep(.pdm-approval-group__table-wrapper) {
  max-height: 240px;
  overflow: auto;
}

:deep(.pdm-approval__table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  color: #141413;
}

:deep(.pdm-approval__table th),
:deep(.pdm-approval__table td) {
  padding: 7px 8px;
  text-align: left;
  border-bottom: 1px solid #f0eee6;
  white-space: nowrap;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
}

:deep(.pdm-approval__table thead th) {
  position: sticky;
  top: 0;
  background: #faf9f5;
  color: #4d4c48;
  font-weight: 500;
  z-index: 1;
}

:deep(.pdm-approval__checkbox-col) {
  width: 30px;
  padding: 4px 6px;
  text-align: center;
}

:deep(.pdm-approval__checkbox) {
  margin: 0;
  cursor: pointer;
  accent-color: #c96442;
}

:deep(.pdm-approval__checkbox:disabled) {
  cursor: not-allowed;
}

:deep(.pdm-approval__row--skipped td) {
  color: #87867f;
  text-decoration: line-through;
}

:deep(.pdm-approval__approve) {
  align-self: flex-start;
  margin-top: 2px;
}

:deep(.task-card__actions) {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

:deep(.task-action-btn) {
  height: 30px;
  min-width: 58px;
  padding: 0 12px;
  font-size: 12px;
  font-weight: 500;
  border-radius: var(--yamato-radius-md);
  border: 1px solid transparent;
  cursor: pointer;
  transition: background 0.18s ease, border-color 0.18s ease, color 0.18s ease, opacity 0.18s ease, transform 0.18s ease,
    box-shadow 0.18s ease;

  &:focus-visible {
    outline: none;
    box-shadow: var(--yamato-focus-ring);
  }

  &:hover:not(:disabled) {
    transform: translateY(-1px);
  }

  &:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
}

:deep(.task-action-btn--danger) {
  background: var(--yamato-color-danger-soft);
  color: var(--yamato-color-danger);
  border-color: rgba(181, 51, 51, 0.24);
  box-shadow: 0 0 0 1px rgba(181, 51, 51, 0.11);

  &:hover:not(:disabled) {
    background: rgba(181, 51, 51, 0.14);
    border-color: rgba(181, 51, 51, 0.32);
  }
}

:deep(.task-action-btn--neutral) {
  background: #ffffff;
  color: var(--yamato-color-text-primary);
  border-color: var(--yamato-color-border-subtle);
  box-shadow: 0 0 0 1px #f0eee6;

  &:hover:not(:disabled) {
    background: #f4f2ea;
    border-color: #d1cfc5;
  }
}

:deep(.task-action-btn--accent) {
  background: var(--yamato-color-accent);
  color: var(--yamato-color-text-on-dark);
  border-color: rgba(201, 100, 66, 0.88);
  box-shadow: 0 0 0 1px rgba(201, 100, 66, 0.38);

  &:hover:not(:disabled) {
    background: var(--yamato-color-accent-hover);
    border-color: rgba(217, 119, 87, 0.92);
  }
}

.result-modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
}

.result-modal {
  width: min(860px, 92vw);
  max-height: 85vh;
  background: var(--yamato-color-surface);
  border-radius: var(--yamato-radius-lg);
  padding: 16px;
  display: flex;
  flex-direction: column;
  box-shadow: var(--yamato-shadow-overlay);
}

.result-modal__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.result-modal__header h3 {
  margin: 0;
  font-size: 21px;
  line-height: 1.19;
  color: var(--yamato-color-text-primary);
}

.icon-btn {
  border: 1px solid var(--yamato-color-border-subtle);
  background: var(--yamato-color-surface);
  color: var(--yamato-color-text-primary);
  border-radius: var(--yamato-radius-sm);
  padding: 6px 10px;
  cursor: pointer;

  &:focus-visible {
    outline: none;
    box-shadow: var(--yamato-focus-ring);
  }
}

.result-modal__content {
  overflow: auto;
}

.result-compact-tip {
  margin: 8px 0;
  padding: 8px 10px;
  border-radius: var(--yamato-radius-sm);
  background: var(--yamato-color-warning-soft);
  color: var(--yamato-color-warning);
  font-size: 12px;
}

.result-json {
  background: var(--yamato-color-surface-alt);
  border-radius: var(--yamato-radius-sm);
  padding: 12px;
  font-size: 12px;
  line-height: 1.5;
  overflow: auto;
}

@media (max-width: 1200px) {
  .columns {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 860px) {
  .quotation-page {
    padding: 20px 16px 12px;
  }

  .quotation-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .quotation-title {
    font-size: 28px;
  }

  :deep(.task-card__progress) {
    gap: 8px;
    padding: 7px;
  }

  :deep(.task-progress-ring),
  :deep(.task-progress-ring__svg) {
    width: 52px;
    height: 52px;
    flex-basis: 52px;
  }

  :deep(.task-card__actions) {
    gap: 6px;
  }

  :deep(.task-action-btn) {
    flex: 1 1 calc(50% - 6px);
    min-width: 0;
  }
}
</style>


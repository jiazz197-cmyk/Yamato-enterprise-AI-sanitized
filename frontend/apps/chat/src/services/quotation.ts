import { authorizedFetch, handleApiError, apiRequest } from './api'
import type {
  ApproveQuotationTaskResponse,
  CancelQuotationTaskResponse,
  CreateQuotationTaskResponse,
  DeleteQuotationTaskResponse,
  ListQuotationTasksParams,
  QuotationTaskItem,
  QuotationTaskListResponse,
} from '../types/quotation'

export const createQuotationTask = async (
  file: File,
  taskName?: string
): Promise<CreateQuotationTaskResponse> => {
  const formData = new FormData()
  formData.append('file', file)
  const normalizedTaskName = String(taskName ?? '').trim()
  if (normalizedTaskName) {
    formData.append('task_name', normalizedTaskName)
  }

  const response = await authorizedFetch(
    '/quotation/tasks',
    {
      method: 'POST',
      body: formData,
    },
    { jsonContentType: false }
  )

  if (!response.ok) {
    await handleApiError(response)
  }

  return response.json()
}

export const listQuotationTasks = async (
  params?: ListQuotationTasksParams
): Promise<QuotationTaskListResponse> => {
  const query = new URLSearchParams()
  if (params?.status) {
    query.set('status', params.status)
  }
  if (params?.ownerUsername) {
    query.set('owner_username', params.ownerUsername)
  }
  if (typeof params?.limit === 'number') {
    query.set('limit', String(params.limit))
  }
  if (params?.fullResult) {
    query.set('full_result', 'true')
  }
  if (params?.activeOnly) {
    query.set('active_only', 'true')
  }

  const queryString = query.toString()
  const endpoint = queryString ? `/quotation/tasks?${queryString}` : '/quotation/tasks'
  return apiRequest<QuotationTaskListResponse>(endpoint, { signal: params?.signal })
}

export const listActiveQuotationTasks = async (params?: {
  ownerUsername?: string
  signal?: AbortSignal
}): Promise<QuotationTaskListResponse> => {
  return listQuotationTasks({
    ownerUsername: params?.ownerUsername,
    activeOnly: true,
    limit: 100,
    signal: params?.signal,
  })
}

export const getQuotationTask = async (
  taskId: string,
  params?: { fullResult?: boolean }
): Promise<QuotationTaskItem> => {
  const query = new URLSearchParams()
  if (params?.fullResult) {
    query.set('full_result', 'true')
  }
  const queryString = query.toString()
  const endpoint = `/quotation/tasks/${encodeURIComponent(taskId)}${queryString ? `?${queryString}` : ''}`
  return apiRequest<QuotationTaskItem>(endpoint)
}

export const cancelQuotationTask = async (taskId: string): Promise<CancelQuotationTaskResponse> => {
  return apiRequest<CancelQuotationTaskResponse>(`/quotation/tasks/${encodeURIComponent(taskId)}/cancel`, {
    method: 'POST',
  })
}

export const approveQuotationTask = async (
  taskId: string,
  approvedPartids: string[],
  extraPartids: string[] = []
): Promise<ApproveQuotationTaskResponse> => {
  return apiRequest<ApproveQuotationTaskResponse>(`/quotation/tasks/${encodeURIComponent(taskId)}/approve`, {
    method: 'POST',
    body: JSON.stringify({
      approved_partids: approvedPartids,
      extra_partids: extraPartids,
    }),
  })
}

export const deleteQuotationTask = async (taskId: string): Promise<DeleteQuotationTaskResponse> => {
  return apiRequest<DeleteQuotationTaskResponse>(`/quotation/tasks/${encodeURIComponent(taskId)}`, {
    method: 'DELETE',
  })
}

const parseFileNameFromDisposition = (
  contentDisposition: string | null,
  fallback = 'quotation-task-file.pdf'
): string => {
  if (!contentDisposition) {
    return fallback
  }

  const utf8Match = contentDisposition.match(/filename\\*=UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) {
    return decodeURIComponent(utf8Match[1])
  }

  const plainMatch = contentDisposition.match(/filename=\"?([^\";]+)\"?/i)
  if (plainMatch?.[1]) {
    return plainMatch[1]
  }

  return fallback
}

export const downloadQuotationTaskFile = async (taskId: string): Promise<{ blob: Blob; filename: string }> => {
  const response = await authorizedFetch(`/quotation/tasks/${encodeURIComponent(taskId)}/file`, {
    method: 'GET',
  })

  if (!response.ok) {
    await handleApiError(response)
  }

  const blob = await response.blob()
  const filename = parseFileNameFromDisposition(response.headers.get('content-disposition'))
  return { blob, filename }
}

export const downloadQuotationU8ByTypeWorkbook = async (
  taskId: string
): Promise<{ blob: Blob; filename: string }> => {
  const response = await authorizedFetch(
    `/quotation/tasks/${encodeURIComponent(taskId)}/u8-by-type-workbook`,
    { method: 'GET' }
  )

  if (!response.ok) {
    await handleApiError(response)
  }

  const blob = await response.blob()
  const filename = parseFileNameFromDisposition(
    response.headers.get('content-disposition'),
    'u8_by_type.xlsx'
  )
  return { blob, filename }
}


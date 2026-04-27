import { authorizedFetch, handleApiError, apiRequest } from './api'
import type {
  ApproveQuotationTaskResponse,
  CancelQuotationTaskResponse,
  CreateQuotationTaskResponse,
  QuotationTaskItem,
  QuotationTaskListResponse,
} from '../types/quotation'

export const createQuotationTask = async (file: File): Promise<CreateQuotationTaskResponse> => {
  const formData = new FormData()
  formData.append('file', file)

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

export const listQuotationTasks = async (params?: {
  status?: string
  ownerUsername?: string
  limit?: number
}): Promise<QuotationTaskListResponse> => {
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

  const queryString = query.toString()
  const endpoint = queryString ? `/quotation/tasks?${queryString}` : '/quotation/tasks'
  return apiRequest<QuotationTaskListResponse>(endpoint)
}

export const getQuotationTask = async (taskId: string): Promise<QuotationTaskItem> => {
  return apiRequest<QuotationTaskItem>(`/quotation/tasks/${encodeURIComponent(taskId)}`)
}

export const cancelQuotationTask = async (taskId: string): Promise<CancelQuotationTaskResponse> => {
  return apiRequest<CancelQuotationTaskResponse>(`/quotation/tasks/${encodeURIComponent(taskId)}/cancel`, {
    method: 'POST',
  })
}

export const approveQuotationTask = async (
  taskId: string,
  approvedPartids: string[]
): Promise<ApproveQuotationTaskResponse> => {
  return apiRequest<ApproveQuotationTaskResponse>(`/quotation/tasks/${encodeURIComponent(taskId)}/approve`, {
    method: 'POST',
    body: JSON.stringify({ approved_partids: approvedPartids }),
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


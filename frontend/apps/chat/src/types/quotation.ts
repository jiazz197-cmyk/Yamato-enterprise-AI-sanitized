export type QuotationTaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface QuotationTaskItem {
  task_id: string
  status: QuotationTaskStatus
  progress: number
  message: string
  owner_id: string
  owner_username: string
  uploaded_file_name: string
  uploaded_file_content_type: string
  uploaded_file_size: number
  created_at: string
  started_at?: string | null
  completed_at?: string | null
  result?: Record<string, unknown> | null
  error?: string | null
}

export interface QuotationTaskListResponse {
  total: number
  items: QuotationTaskItem[]
}

export interface CreateQuotationTaskResponse {
  task_id: string
  status: QuotationTaskStatus
  message: string
  queue_position: number
}

export interface CancelQuotationTaskResponse {
  success: boolean
  message: string
  task_id: string
}


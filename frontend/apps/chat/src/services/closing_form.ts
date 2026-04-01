import { apiRequest } from './api'

export interface ClosingFormRecord {
  id: string
  text: string
  file_name?: string | null
  upload_time: string | null
  uploader: string
  status: string
}

export interface ClosingFormListResponse {
  records: ClosingFormRecord[]
}

export const submitClosingForm = async (payload: Record<string, unknown>): Promise<void> => {
  await apiRequest('/closing-form/submit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export const listClosingFormRecords = async (): Promise<ClosingFormRecord[]> => {
  const data = await apiRequest<ClosingFormListResponse>('/closing-form/list')
  return data.records ?? []
}

export const approveClosingForm = async (formId: string): Promise<void> => {
  await apiRequest(`/closing-form/approve/${formId}`, { method: 'PATCH' })
}

export const rejectClosingForm = async (formId: string): Promise<void> => {
  await apiRequest(`/closing-form/reject/${formId}`, { method: 'PATCH' })
}

export const deleteApprovedClosingForm = async (formId: string): Promise<void> => {
  await apiRequest(`/closing-form/approved/${formId}`, { method: 'DELETE' })
}

export const listCollection2Records = async (): Promise<ClosingFormRecord[]> => {
  const data = await apiRequest<ClosingFormListResponse>('/closing-form/collection2/list')
  return data.records ?? []
}

export const deleteCollection2Record = async (recordId: string): Promise<void> => {
  await apiRequest(`/closing-form/collection2/${recordId}`, { method: 'DELETE' })
}

export type QuotationTaskStatus =
  | 'queued'
  | 'running'
  | 'awaiting_approval'
  | 'completed'
  | 'failed'
  | 'cancelled'

export interface QuotationPdmItem {
  CHINANAME?: string
  PARTID?: string
  QUERY_INDEX?: number
  QUERY_KEYWORDS?: string[]
  QUERY_EXPANDED_KEYWORDS?: string[]
  [key: string]: unknown
}

export interface QuotationPdmResult {
  total?: number
  items?: QuotationPdmItem[]
  [key: string]: unknown
}

export interface QuotationU8Item {
  __root_inv_code?: string
  [key: string]: unknown
}

export interface QuotationU8Result {
  total?: number
  items?: QuotationU8Item[]
  [key: string]: unknown
}

export interface QuotationU8ResultByTypeItem {
  type?: string
  u8_parent_inv_codes?: string[]
  total?: number
  items?: QuotationU8Item[]
  [key: string]: unknown
}

export interface QuotationU8ResultByType {
  total?: number
  items?: QuotationU8ResultByTypeItem[]
  [key: string]: unknown
}

export interface QuotationU8TypeSummaryItem {
  type?: string
  u8_parent_inv_codes?: string[]
  total?: number
  [key: string]: unknown
}

export interface QuotationU8TypeMappingItem {
  query_index?: number
  type?: string
  u8_parent_inv_code?: string
  matched?: boolean
  [key: string]: unknown
}

export interface QuotationU8ResultTypeSummary {
  total_types?: number
  total_items?: number
  matched_root_codes?: number
  unmatched_root_codes?: string[]
  types?: QuotationU8TypeSummaryItem[]
  mapping?: QuotationU8TypeMappingItem[]
  [key: string]: unknown
}

export interface QuotationTaskResult {
  __result_compact?: boolean
  __result_omitted?: boolean
  keywords_payload?: Record<string, unknown>
  pdm_result?: QuotationPdmResult
  pdm_partids?: string[]
  approved_partids?: string[]
  u8_parent_inv_codes?: string[]
  pdm_to_u8_code_mappings?: Array<{
    pdm_partid?: string
    u8_parent_inv_code?: string
    [key: string]: unknown
  }>
  u8_result?: QuotationU8Result
  u8_result_by_type?: QuotationU8ResultByType
  u8_result_type_summary?: QuotationU8ResultTypeSummary
  /** MinIO object path for Phase2 multi-sheet workbook (server-side). */
  u8_result_by_type_xlsx_minio_path?: string
  /** Suggested download filename for ``GET .../u8-by-type-workbook``. */
  u8_result_by_type_xlsx_filename?: string
  temp_image_minio_path?: string
  temp_image_url?: string
  raw_extracted_info?: Record<string, unknown>
  cleanup?: Record<string, unknown>
  [key: string]: unknown
}

export interface ApproveQuotationTaskResponse {
  success: boolean
  message: string
  task_id: string
  status: QuotationTaskStatus
  approved_count: number
}

export interface QuotationTaskItem {
  task_id: string
  status: QuotationTaskStatus
  progress: number
  message: string
  owner_id: string
  owner_username: string
  uploaded_file_name: string
  display_name: string
  uploaded_file_content_type: string
  uploaded_file_size: number
  created_at: string
  started_at?: string | null
  completed_at?: string | null
  result?: QuotationTaskResult | null
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

export interface DeleteQuotationTaskResponse {
  success: boolean
  message: string
  task_id: string
  cleanup: Record<string, unknown>
  task_record_removed: boolean
}

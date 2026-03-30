<template>
  <div class="page">
    <div class="page-header">
      <div class="page-header__left">
        <h1 class="page-header__title">知识库管理</h1>
      </div>
    </div>

    <div class="page__content">
      <div class="records">
        <div class="records__toolbar">
          <button class="records__refresh" type="button" :disabled="loadingRecords" @click="loadRecords">
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              :class="{ 'records__refresh-icon--spinning': loadingRecords }"
              class="records__refresh-icon"
              aria-hidden="true"
            >
              <path
                d="M1 4v6h6M23 20v-6h-6"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
              <path
                d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4-4.64 4.36A9 9 0 0 1 3.51 15"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            刷新
          </button>
          <span class="records__count">共 {{ records.length }} 条</span>
        </div>

        <div v-if="loadingRecords" class="records__loading">
          <div class="records__loading-dots">
            <span></span><span></span><span></span>
          </div>
        </div>

        <div v-else-if="records.length === 0" class="records__empty">
          暂无记录
        </div>

        <div v-else class="records__list">
          <div
            v-for="record in records"
            :key="record.id"
            class="record-card"
            :class="{ 'record-card--expanded': expandedId === record.id }"
          >
            <div class="record-card__header" @click="toggleExpand(record.id)">
              <div class="record-card__meta">
                <span class="record-card__time">{{ record.upload_time || '—' }}</span>
                <span v-if="record.uploader" class="record-card__uploader">{{ record.uploader }}</span>
                <span v-if="record.file_name" class="record-card__filename" :title="record.file_name">
                  {{ record.file_name }}
                </span>
                <span class="record-card__summary">{{ getSummary(record.text) }}</span>
              </div>
              <div class="record-card__right">
                <button
                  class="delete-btn"
                  :disabled="deletingId === record.id"
                  @click.stop="openDeleteDialog(record.id)"
                >
                  {{ deletingId === record.id ? '...' : '删除' }}
                </button>
                <svg
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  class="record-card__chevron"
                  aria-hidden="true"
                >
                  <path
                    d="M6 9l6 6 6-6"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </div>
            </div>

            <div v-if="expandedId === record.id" class="record-card__body">
              <div v-if="record.file_name" class="record-file-row">
                <span class="record-file-row__label">文件名称</span>
                <span class="record-file-row__value">{{ record.file_name }}</span>
              </div>
              <div v-if="hasStructuredFields(record.text)" class="record-fields">
                <div
                  v-for="field in parseFields(record.text)"
                  :key="field.label"
                  class="record-field"
                >
                  <span class="record-field__label">{{ field.label }}</span>
                  <span class="record-field__value">{{ field.value }}</span>
                </div>
              </div>
              <div v-else class="record-raw-text">{{ record.text }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <ConfirmDialog
      v-model="showDeleteDialog"
      title="删除知识库记录"
      message="确定要删除这条记录吗？此操作无法撤销。"
      type="danger"
      confirm-text="删除"
      cancel-text="取消"
      @confirm="confirmDelete"
    />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ConfirmDialog, useToast } from '@yamato/components'
import { deleteCollection2Record, listCollection2Records, type ClosingFormRecord } from '../services/closing_form'

interface ParsedField {
  label: string
  value: string
}

const { showSuccess, showError } = useToast()

const records = ref<ClosingFormRecord[]>([])
const loadingRecords = ref(false)
const expandedId = ref<string | null>(null)
const deletingId = ref<string | null>(null)
const showDeleteDialog = ref(false)
const recordToDelete = ref<string | null>(null)

const loadRecords = async () => {
  loadingRecords.value = true
  try {
    records.value = await listCollection2Records()
  } catch (err: any) {
    showError(err?.message || '加载失败')
  } finally {
    loadingRecords.value = false
  }
}

const toggleExpand = (id: string) => {
  expandedId.value = expandedId.value === id ? null : id
}

const parseFields = (text: string): ParsedField[] => {
  return text
    .split(/,\s*/)
    .map((part) => {
      const trimmed = part.trim()
      if (!trimmed) return null
      const match = /^([^：:\n]{1,24})[：:]\s*(.+)$/.exec(trimmed)
      if (!match) return null
      const label = match[1].trim()
      const value = match[2].trim()
      if (!label || !value) return null
      return { label, value }
    })
    .filter((f): f is ParsedField => f !== null)
}

const hasStructuredFields = (text: string): boolean => {
  const fields = parseFields(text)
  // Closing-form style records have many key-value pairs.
  return fields.length >= 3
}

const getSummary = (text: string): string => {
  const fields = parseFields(text)
  const customer = fields.find((f) => f.label === '客户名称')?.value ?? ''
  const model = fields.find((f) => f.label === '型号规格')?.value ?? ''
  const qty = fields.find((f) => f.label === '数量')?.value ?? ''
  const parts = [customer, model, qty ? `×${qty}` : ''].filter(Boolean)
  return parts.join('  ') || text.slice(0, 50)
}

const openDeleteDialog = (id: string) => {
  recordToDelete.value = id
  showDeleteDialog.value = true
}

const confirmDelete = async () => {
  if (!recordToDelete.value) return

  const id = recordToDelete.value
  deletingId.value = id
  try {
    await deleteCollection2Record(id)
    records.value = records.value.filter((record) => record.id !== id)
    if (expandedId.value === id) {
      expandedId.value = null
    }
    showSuccess('删除成功')
  } catch (err: any) {
    showError(err?.message || '删除失败')
  } finally {
    deletingId.value = null
    recordToDelete.value = null
    showDeleteDialog.value = false
  }
}

onMounted(() => {
  void loadRecords()
})
</script>

<style scoped lang="scss">
.page {
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 32px 32px 24px;
  box-sizing: border-box;
  overflow: auto;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 24px;
  flex-shrink: 0;
}

.page-header__left {
  display: flex;
  align-items: baseline;
  gap: 32px;
}

.page-header__title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: #202124;
}

.page__content {
  background: #ffffff;
  border-radius: 12px;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.08);
  padding: 32px;
  flex: 1;
  display: flex;
  justify-content: center;
}

.records {
  width: 100%;
  max-width: 960px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.records__toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.records__refresh {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 999px;
  border: 1px solid #d2e3fc;
  background: #f8f9fa;
  color: #1a73e8;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s ease;

  &:hover:not(:disabled) {
    background: #e8f0fe;
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
}

.records__refresh-icon {
  flex-shrink: 0;
  transition: transform 0.4s linear;

  &--spinning {
    animation: spin 0.8s linear infinite;
  }
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.records__count {
  font-size: 13px;
  color: #5f6368;
}

.records__loading {
  display: flex;
  justify-content: center;
  padding: 40px 0;
}

.records__loading-dots {
  display: flex;
  gap: 6px;

  span {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: #1a73e8;
    animation: dot-bounce 1.2s ease-in-out infinite;

    &:nth-child(2) { animation-delay: 0.2s; }
    &:nth-child(3) { animation-delay: 0.4s; }
  }
}

@keyframes dot-bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

.records__empty {
  padding: 48px 0;
  text-align: center;
  font-size: 14px;
  color: #9aa0a6;
}

.records__list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.record-card {
  border-radius: 10px;
  border: 1px solid #e8eaed;
  background: #ffffff;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(60, 64, 67, 0.08);
  transition: box-shadow 0.2s ease;
  border-left: 3px solid #34a853;

  &:hover {
    box-shadow: 0 2px 6px rgba(60, 64, 67, 0.15);
  }

  &--expanded {
    border-color: #c5d9f8;
  }
}

.record-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  cursor: pointer;
  user-select: none;
}

.record-card__meta {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1;
}

.record-card__time {
  font-size: 12px;
  color: #9aa0a6;
  white-space: nowrap;
  flex-shrink: 0;
}

.record-card__uploader {
  font-size: 12px;
  color: #9aa0a6;
  white-space: nowrap;
  flex-shrink: 0;
  background: #f1f3f4;
  padding: 1px 7px;
  border-radius: 999px;
}

.record-card__filename {
  font-size: 12px;
  color: #5f6368;
  white-space: nowrap;
  flex-shrink: 1;
  min-width: 0;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  background: #eef3fb;
  padding: 1px 7px;
  border-radius: 999px;
}

.record-card__summary {
  font-size: 13px;
  color: #202124;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.record-card__right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  margin-left: 12px;
}

.record-card__chevron {
  flex-shrink: 0;
  color: #9aa0a6;
  transition: transform 0.2s ease;

  .record-card--expanded & {
    transform: rotate(180deg);
  }
}

.delete-btn {
  height: 26px;
  padding: 0 12px;
  border-radius: 999px;
  border: none;
  color: #c5221f;
  background: #fce8e6;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s ease, opacity 0.15s ease;
  white-space: nowrap;

  &:hover:not(:disabled) {
    background: #fad2cf;
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
}

.record-card__body {
  border-top: 1px solid #e8eaed;
  padding: 16px;
  background: #fafbfc;
}

.record-file-row {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 12px;
  margin-bottom: 12px;
  align-items: start;
}

.record-file-row__label {
  font-size: 12px;
  color: #9aa0a6;
  font-weight: 600;
}

.record-file-row__value {
  font-size: 13px;
  color: #202124;
  line-height: 1.7;
  text-align: justify;
  text-justify: inter-ideograph;
  word-break: break-all;
}

.record-fields {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}

.record-field {
  display: grid;
  grid-template-columns: 96px 1fr;
  gap: 12px;
  align-items: start;
  padding-bottom: 8px;
  border-bottom: 1px dashed #e5e8ee;
}

.record-field__label {
  font-size: 12px;
  color: #9aa0a6;
  font-weight: 600;
  text-align: left;
}

.record-field__value {
  font-size: 13px;
  color: #202124;
  line-height: 1.7;
  text-align: justify;
  text-justify: inter-ideograph;
  word-break: break-word;
}

.record-raw-text {
  font-size: 13px;
  color: #202124;
  line-height: 1.8;
  text-align: justify;
  text-justify: inter-ideograph;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>

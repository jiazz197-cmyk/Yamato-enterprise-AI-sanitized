<template>
  <div class="page">
    <div class="page-header">
      <div class="page-header__left">
        <h1 class="page-header__title">报单填写</h1>
        <div class="page__tabs">
      <button
        class="page__tab"
        :class="{ 'page__tab--active': activeTab === 'form' }"
        type="button"
        @click="activeTab = 'form'"
      >
        填写表单
        </button>
        <button
          class="page__tab"
          :class="{ 'page__tab--active': activeTab === 'records' }"
          type="button"
          @click="switchToRecords"
        >
          {{ isAdmin ? '全部表单' : '我的表单' }}
        </button>
      </div>
    </div>
  </div>

    <div class="page__content">

      <!-- 填写表单 -->
      <form v-if="activeTab === 'form'" class="form" @submit.prevent="submitForm">

        <section class="form-section">
          <div class="form-section__title">基本信息</div>
          <div class="form-grid">
            <div class="form-field">
              <label class="form-field__label" for="closing_date">成交时间</label>
              <input
                id="closing_date"
                v-model="form.closing_date"
                type="date"
                class="form-field__input"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="customer_name">客户名称</label>
              <input
                id="customer_name"
                v-model="form.customer_name"
                type="text"
                class="form-field__input"
                placeholder="请输入客户名称"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="product_type">产品类型</label>
              <input
                id="product_type"
                v-model="form.product_type"
                type="text"
                class="form-field__input"
                placeholder="请输入产品类型"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="model_spec">型号规格</label>
              <input
                id="model_spec"
                v-model="form.model_spec"
                type="text"
                class="form-field__input"
                placeholder="请输入型号规格"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="quantity">数量</label>
              <input
                id="quantity"
                v-model.number="form.quantity"
                type="number"
                min="0"
                class="form-field__input"
                placeholder="请输入数量"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="price_excluding_tax">不含税单价</label>
              <input
                id="price_excluding_tax"
                v-model.number="form.price_excluding_tax"
                type="number"
                min="0"
                step="0.01"
                class="form-field__input"
                placeholder="请输入不含税单价"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="production_number">生产编号</label>
              <input
                id="production_number"
                v-model="form.production_number"
                type="text"
                class="form-field__input"
                placeholder="请输入生产编号"
              />
            </div>
          </div>
        </section>

        <section class="form-section">
          <div class="form-section__title">物料与称重</div>
          <div class="form-grid">
            <div class="form-field">
              <label class="form-field__label" for="material_name">物料名称</label>
              <input
                id="material_name"
                v-model="form.material_name"
                type="text"
                class="form-field__input"
                placeholder="请输入物料名称"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="weighing_spec">称重规格</label>
              <input
                id="weighing_spec"
                v-model="form.weighing_spec"
                type="text"
                class="form-field__input"
                placeholder="例如：10g"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="speed">速度（次/分）</label>
              <input
                id="speed"
                v-model.number="form.speed"
                type="number"
                min="0"
                class="form-field__input"
                placeholder="请输入速度"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="precision">精度</label>
              <input
                id="precision"
                v-model="form.precision"
                type="text"
                class="form-field__input"
                placeholder="例如：≤1g"
              />
            </div>
          </div>
        </section>

        <section class="form-section">
          <div class="form-section__title">零部件配置</div>
          <div class="form-grid">
            <div class="form-field">
              <label class="form-field__label" for="top_cone_type">顶锥形式</label>
              <input
                id="top_cone_type"
                v-model="form.top_cone_type"
                type="text"
                class="form-field__input"
                placeholder="请输入顶锥形式"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="linear_vibration_type">线振形式</label>
              <input
                id="linear_vibration_type"
                v-model="form.linear_vibration_type"
                type="text"
                class="form-field__input"
                placeholder="请输入线振形式"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="material_layer_ring">料层圈</label>
              <input
                id="material_layer_ring"
                v-model="form.material_layer_ring"
                type="text"
                class="form-field__input"
                placeholder="请输入料层圈"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="feed_hopper">进料斗</label>
              <input
                id="feed_hopper"
                v-model="form.feed_hopper"
                type="text"
                class="form-field__input"
                placeholder="请输入进料斗"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="metering_hopper">计量斗</label>
              <input
                id="metering_hopper"
                v-model="form.metering_hopper"
                type="text"
                class="form-field__input"
                placeholder="请输入计量斗"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="memory_hopper">存储斗</label>
              <input
                id="memory_hopper"
                v-model="form.memory_hopper"
                type="text"
                class="form-field__input"
                placeholder="请输入存储斗"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="chute_angle">溜槽角度</label>
              <input
                id="chute_angle"
                v-model="form.chute_angle"
                type="text"
                class="form-field__input"
                placeholder="例如：50°"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="collection_hopper_type">集合斗形式</label>
              <input
                id="collection_hopper_type"
                v-model="form.collection_hopper_type"
                type="text"
                class="form-field__input"
                placeholder="请输入集合斗形式"
              />
            </div>
            <div class="form-field">
              <label class="form-field__label" for="scale_type">秤体类型</label>
              <input
                id="scale_type"
                v-model="form.scale_type"
                type="text"
                class="form-field__input"
                placeholder="请输入秤体类型"
              />
            </div>
          </div>
        </section>

        <div class="form-actions">
          <button class="form-actions__reset" type="button" @click="resetForm">重置</button>
          <button class="form-actions__submit" type="submit" :disabled="submitting">
            {{ submitting ? '提交中…' : '提交' }}
          </button>
        </div>

      </form>

      <!-- 表单记录 -->
      <div v-else class="records">

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
          暂无提交记录
        </div>

        <div v-else class="records__list">
          <div
            v-for="record in records"
            :key="record.id"
            class="record-card"
            :class="{
              'record-card--expanded': expandedId === record.id,
              'record-card--pending': record.status === 'pending',
              'record-card--approved': record.status === 'approved',
              'record-card--rejected': record.status === 'rejected',
            }"
          >
            <div class="record-card__header" @click="toggleExpand(record.id)">
              <div class="record-card__meta">
                <span class="record-card__time">{{ record.upload_time || '—' }}</span>
                <span v-if="isAdmin && record.uploader" class="record-card__uploader">
                  {{ record.uploader }}
                </span>
                <span class="record-card__summary">{{ getSummary(record.text) }}</span>
              </div>
              <div class="record-card__right">
                <span class="status-badge" :class="`status-badge--${record.status}`">
                  <span class="status-badge__dot"></span>
                  {{ record.status === 'approved' ? '已通过' : record.status === 'rejected' ? '不通过' : '待审批' }}
                </span>
                <div v-if="isAdmin && record.status === 'pending'" class="action-buttons">
                  <button
                    class="approve-btn reject-btn"
                    :disabled="approvingId === record.id"
                    @click.stop="rejectRecord(record.id)"
                  >
                    {{ approvingId === record.id ? '...' : '不通过' }}
                  </button>
                  <button
                    class="approve-btn"
                    :disabled="approvingId === record.id"
                    @click.stop="approveRecord(record.id)"
                  >
                    {{ approvingId === record.id ? '...' : '通过' }}
                  </button>
                </div>
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
              <div class="record-fields">
                <div
                  v-for="field in parseFields(record.text)"
                  :key="field.label"
                  class="record-field"
                >
                  <span class="record-field__label">{{ field.label }}</span>
                  <span class="record-field__value">{{ field.value }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

      </div>

    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useToast } from '@yamato/components'
import { apiRequest } from '../services/api'
import { readUserRole } from '../services/auth'
import { config } from '../config'

interface FormData {
  closing_date: string
  customer_name: string
  product_type: string
  model_spec: string
  quantity: number | null
  price_excluding_tax: number | null
  production_number: string
  material_name: string
  weighing_spec: string
  speed: number | null
  precision: string
  top_cone_type: string
  linear_vibration_type: string
  material_layer_ring: string
  feed_hopper: string
  metering_hopper: string
  memory_hopper: string
  chute_angle: string
  collection_hopper_type: string
  scale_type: string
}

interface FormRecord {
  id: string
  text: string
  upload_time: string | null
  uploader: string
  status: string
}

interface ParsedField {
  label: string
  value: string
}

const { showSuccess, showError } = useToast()

const activeTab = ref<'form' | 'records'>('form')

const isAdmin = computed(() => {
  const role = readUserRole()
  return role === 'admin' || role === 'superuser'
})

const createEmptyForm = (): FormData => ({
  closing_date: '',
  customer_name: '',
  product_type: '',
  model_spec: '',
  quantity: null,
  price_excluding_tax: null,
  production_number: '',
  material_name: '',
  weighing_spec: '',
  speed: null,
  precision: '',
  top_cone_type: '',
  linear_vibration_type: '',
  material_layer_ring: '',
  feed_hopper: '',
  metering_hopper: '',
  memory_hopper: '',
  chute_angle: '',
  collection_hopper_type: '',
  scale_type: '',
})

const form = ref<FormData>(createEmptyForm())
const submitting = ref(false)

const records = ref<FormRecord[]>([])
const loadingRecords = ref(false)
const expandedId = ref<string | null>(null)
const approvingId = ref<string | null>(null)

const resetForm = () => {
  form.value = createEmptyForm()
}

const submitForm = async () => {
  submitting.value = true
  try {
    await apiRequest('/closing-form/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form.value),
    })
    showSuccess('提交成功，等待审批')
    resetForm()
  } catch (err: any) {
    showError(err?.message || err?.detail || '提交失败，请稍后重试')
  } finally {
    submitting.value = false
  }
}

const loadRecords = async () => {
  loadingRecords.value = true
  try {
    const data = await apiRequest<{ records: FormRecord[] }>('/closing-form/list')
    records.value = data.records ?? []
  } catch (err: any) {
    showError(err?.message || '加载失败')
  } finally {
    loadingRecords.value = false
  }
}

const approveRecord = async (formId: string) => {
  approvingId.value = formId
  try {
    await apiRequest(`/closing-form/approve/${formId}`, { method: 'PATCH' })
    const idx = records.value.findIndex((r) => r.id === formId)
    if (idx !== -1) records.value[idx] = { ...records.value[idx], status: 'approved' }
    showSuccess('已审批通过')
  } catch (err: any) {
    showError(err?.message || '审批失败')
  } finally {
    approvingId.value = null
  }
}

const rejectRecord = async (formId: string) => {
  approvingId.value = formId
  try {
    await apiRequest(`/closing-form/reject/${formId}`, { method: 'PATCH' })
    const idx = records.value.findIndex((r) => r.id === formId)
    if (idx !== -1) records.value[idx] = { ...records.value[idx], status: 'rejected' }
    showSuccess('已审批不通过')
  } catch (err: any) {
    showError(err?.message || '操作失败')
  } finally {
    approvingId.value = null
  }
}

const switchToRecords = () => {
  activeTab.value = 'records'
  if (records.value.length === 0) {
    void loadRecords()
  }
}

const toggleExpand = (id: string) => {
  expandedId.value = expandedId.value === id ? null : id
}

const parseFields = (text: string): ParsedField[] => {
  return text
    .split(', ')
    .map((part) => {
      const colonIdx = part.indexOf('：')
      if (colonIdx === -1) return null
      return { label: part.slice(0, colonIdx).trim(), value: part.slice(colonIdx + 1).trim() }
    })
    .filter((f): f is ParsedField => f !== null)
}

const getSummary = (text: string): string => {
  const fields = parseFields(text)
  const customer = fields.find((f) => f.label === '客户名称')?.value ?? ''
  const model = fields.find((f) => f.label === '型号规格')?.value ?? ''
  const qty = fields.find((f) => f.label === '数量')?.value ?? ''
  const parts = [customer, model, qty ? `×${qty}` : ''].filter(Boolean)
  return parts.join('  ')
}
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

.page__tabs {
  display: flex;
  gap: 16px;
  align-items: center;
}

.page__tab {
  padding: 8px 12px;
  border: none;
  background: transparent;
  font-size: 14px;
  color: #5f6368;
  cursor: pointer;
  border-radius: 6px;
  transition: all 0.2s ease;

  &:hover {
    color: #1a73e8;
  }

  &--active {
    color: #1a73e8;
    font-weight: 600;
    background: #e8f0fe;
  }
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

/* ===== 填写表单 ===== */

.form {
  width: 100%;
  max-width: 960px;
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.form-section {
  border-radius: 12px;
  border: 1px solid #e8eaed;
  background: #ffffff;
  padding: 16px 20px 20px;
  box-shadow: 0 1px 2px rgba(60, 64, 67, 0.1);
}

.form-section__title {
  font-size: 14px;
  font-weight: 600;
  color: #1a73e8;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid #e8f0fe;
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px 24px;
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-field__label {
  font-size: 13px;
  font-weight: 500;
  color: #5f6368;
  white-space: nowrap;
}

.form-field__input {
  padding: 7px 10px;
  border-radius: 6px;
  border: 1px solid #dadce0;
  font-size: 13px;
  color: #202124;
  width: 100%;
  box-sizing: border-box;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;

  &:focus {
    outline: none;
    border-color: #1a73e8;
    box-shadow: 0 0 0 2px rgba(26, 115, 232, 0.15);
  }

  &::placeholder {
    color: #bdc1c6;
  }
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.form-actions__reset {
  padding: 8px 20px;
  border-radius: 999px;
  border: 1px solid #dadce0;
  background: #f8f9fa;
  color: #5f6368;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s ease, border-color 0.2s ease;

  &:hover {
    background: #e8eaed;
    border-color: #c1c7cd;
  }
}

.form-actions__submit {
  padding: 8px 24px;
  border-radius: 999px;
  border: none;
  background: #1a73e8;
  color: #ffffff;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s ease;

  &:hover:not(:disabled) {
    background: #185abc;
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
}

/* ===== 表单记录 ===== */

.records {
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

  &:hover {
    box-shadow: 0 2px 6px rgba(60, 64, 67, 0.15);
  }

  &--expanded {
    border-color: #c5d9f8;
  }

  &--pending {
    border-left: 3px solid #f9ab00;
  }

  &--approved {
    border-left: 3px solid #34a853;
  }

  &--rejected {
    border-left: 3px solid #ea4335;
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

/* ===== 状态徽章 ===== */

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  white-space: nowrap;

  &--pending {
    background: #fef7e0;
    color: #b06000;

    .status-badge__dot {
      background: #f9ab00;
    }
  }

  &--approved {
    background: #e6f4ea;
    color: #137333;

    .status-badge__dot {
      background: #34a853;
    }
  }

  &--rejected {
    background: #fce8e6;
    color: #c5221f;

    .status-badge__dot {
      background: #ea4335;
    }
  }
}

.status-badge__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

/* ===== 审批按钮 ===== */

.action-buttons {
  display: flex;
  gap: 8px;
  align-items: center;
}

.approve-btn {
  height: 26px;
  padding: 0 12px;
  border-radius: 999px;
  border: none;
  background: #e6f4ea;
  color: #137333;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s ease, opacity 0.15s ease;
  white-space: nowrap;

  &:hover:not(:disabled) {
    background: #ceead6;
  }

  &:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
}

.reject-btn {
  color: #c5221f;
  background: #fce8e6;

  &:hover:not(:disabled) {
    background: #fad2cf;
  }
}

/* ===== 展开内容 ===== */

.record-card__body {
  border-top: 1px solid #e8eaed;
  padding: 16px;
  background: #fafbfc;
}

.record-fields {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px 24px;
}

.record-field {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.record-field__label {
  font-size: 11px;
  color: #9aa0a6;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.record-field__value {
  font-size: 13px;
  color: #202124;
}
</style>

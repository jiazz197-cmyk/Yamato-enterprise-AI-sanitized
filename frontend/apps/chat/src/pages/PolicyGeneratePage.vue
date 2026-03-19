<template>
  <div class="page">
    <PageHeader title="报单填写" subtitle="填写信息并生成表单文档" />

    <div class="page__content">
      <form class="form" @submit.prevent="submitForm">

        <section class="form-section">
          <div class="form-section__title">基本信息</div>
          <div class="form-grid">
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
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { PageHeader } from '@yamato/components'
import { config } from '../config'

interface FormData {
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

const createEmptyForm = (): FormData => ({
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

const getCurrentUser = (): string => {
  try {
    const raw = localStorage.getItem(config.settingsStorageKey)
    if (!raw) return 'anonymous'
    const parsed = JSON.parse(raw) as { user?: unknown; userId?: unknown }
    return String(parsed.user ?? parsed.userId ?? '').trim() || 'anonymous'
  } catch {
    return 'anonymous'
  }
}

const resetForm = () => {
  form.value = createEmptyForm()
}

const submitForm = async () => {
  submitting.value = true
  try {
    const username = getCurrentUser()
    const response = await fetch(`${config.apiBaseUrl}/closing-form/submit`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Username': username,
      },
      body: JSON.stringify(form.value),
    })
    if (response.ok) {
      alert('提交成功')
      resetForm()
    } else {
      const text = await response.text()
      alert(`提交失败：${response.status} ${text}`)
    }
  } catch (err) {
    alert(`提交失败：${err instanceof Error ? err.message : String(err)}`)
  } finally {
    submitting.value = false
  }
}
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

.form {
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
</style>

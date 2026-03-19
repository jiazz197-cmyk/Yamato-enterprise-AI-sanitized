<template>
  <div class="page">
    <PageHeader title="报单生成" subtitle="填写信息并生成表单文档" />

    <div class="page__content">
      <section class="order-card" aria-label="历史订单信息">
        <header class="order-card__header">
          <div class="order-card__title">历史订单信息</div>
          <div class="order-card__actions">
            <button class="order-card__button" type="button" @click="addRow">
              <span class="order-card__button-icon" aria-hidden="true">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M12 5v14M5 12h14"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                  />
                </svg>
              </span>
              <span>新增一行</span>
            </button>
            <button class="order-card__button order-card__button--primary" type="button" @click="submitOrders">
              <span>提交</span>
            </button>
          </div>
        </header>

        <div class="order-card__body">
          <div class="order-table-wrapper">
            <table class="order-table">
              <thead>
                <tr>
                  <th scope="col">子件名称</th>
                  <th scope="col">材料编码</th>
                  <th scope="col">数量</th>
                  <th scope="col">单价</th>
                  <th scope="col">总价</th>
                  <th scope="col" class="order-table__col--actions">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in orderRows" :key="row.id">
                  <td>
                    <input
                      v-model="row.partName"
                      type="text"
                      class="order-table__input"
                      placeholder="请输入子件名称"
                    />
                  </td>
                  <td>
                    <input
                      v-model="row.materialCode"
                      type="text"
                      class="order-table__input"
                      placeholder="请输入材料编码"
                    />
                  </td>
                  <td>
                    <input
                      v-model="row.quantity"
                      type="number"
                      min="0"
                      class="order-table__input order-table__input--number"
                      placeholder="0"
                    />
                  </td>
                  <td>
                    <input
                      v-model="row.unitPrice"
                      type="number"
                      min="0"
                      step="0.01"
                      class="order-table__input order-table__input--number"
                      placeholder="0.00"
                    />
                  </td>
                  <td>
                    <input
                      v-model="row.totalPrice"
                      type="number"
                      min="0"
                      step="0.01"
                      class="order-table__input order-table__input--number"
                      placeholder="0.00"
                    />
                  </td>
                  <td class="order-table__col--actions">
                    <button
                      class="order-table__delete-button"
                      type="button"
                      title="删除该行"
                      aria-label="删除该行订单数据"
                      @click="removeRow(row.id)"
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <path
                          d="M5 7h14M10 11v6M14 11v6M9 7l1-3h4l1 3M7 7v12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2V7"
                          stroke="currentColor"
                          stroke-width="2"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                        />
                      </svg>
                    </button>
                  </td>
                </tr>
                <tr class="order-table__add-row">
                  <td colspan="6">
                    <button class="order-table__add-row-button" type="button" @click="addRow">
                      <span class="order-table__add-row-icon" aria-hidden="true">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                          <path
                            d="M12 5v14M5 12h14"
                            stroke="currentColor"
                            stroke-width="2"
                            stroke-linecap="round"
                          />
                        </svg>
                      </span>
                      <span class="order-table__add-row-text">新增一行订单数据</span>
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { PageHeader } from '@yamato/components'

interface OrderRow {
  id: number
  partName: string
  materialCode: string
  quantity: string
  unitPrice: string
  totalPrice: string
}

const createEmptyRow = (): OrderRow => ({
  id: Date.now() + Math.floor(Math.random() * 1000),
  partName: '',
  materialCode: '',
  quantity: '',
  unitPrice: '',
  totalPrice: '',
})

const orderRows = ref<OrderRow[]>([createEmptyRow()])

const addRow = () => {
  orderRows.value.push(createEmptyRow())
}

const removeRow = (id: number) => {
  if (orderRows.value.length === 1) {
    orderRows.value = [createEmptyRow()]
    return
  }

  orderRows.value = orderRows.value.filter((row) => row.id !== id)
}

const submitOrders = () => {
  // 这里预留后续与后端接口对接的位置
  void orderRows
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

.order-card {
  border-radius: 12px;
  border: 1px solid #e8eaed;
  background: #ffffff;
  padding: 16px 20px 20px;
  box-shadow: 0 1px 2px rgba(60, 64, 67, 0.1);
  max-width: 100%;
}

.order-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 12px;
}

.order-card__title {
  font-size: 16px;
  font-weight: 600;
  color: #202124;
}

.order-card__actions {
  display: flex;
  gap: 8px;
}

.order-card__button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 999px;
  border: 1px solid #d2e3fc;
  background: #f8f9fa;
  color: #1a73e8;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;

  &:hover {
    background: #e8f0fe;
    border-color: #c1d4f7;
    box-shadow: 0 1px 2px rgba(60, 64, 67, 0.15);
  }
}

.order-card__button--primary {
  background: #1a73e8;
  border-color: #1a73e8;
  color: #ffffff;

  &:hover {
    background: #185abc;
    border-color: #185abc;
  }
}

.order-card__button-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.order-card__body {
  margin-top: 4px;
}

.order-table-wrapper {
  overflow-x: auto;
}

.order-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  color: #202124;
  min-width: 720px;
}

.order-table th,
.order-table td {
  border: 1px solid #e8eaed;
  padding: 8px 10px;
  text-align: left;
  background-color: #ffffff;
}

.order-table th {
  background: #f8f9fa;
  font-weight: 500;
  color: #5f6368;
  white-space: nowrap;
}

.order-table__input {
  width: 100%;
  padding: 4px 6px;
  border-radius: 4px;
  border: 1px solid #dadce0;
  font-size: 13px;
  color: #202124;
  box-sizing: border-box;

  &:focus {
    outline: none;
    border-color: #1a73e8;
    box-shadow: 0 0 0 1px rgba(26, 115, 232, 0.2);
  }
}

.order-table__input--number {
  text-align: right;
}

.order-table__col--actions {
  width: 64px;
  text-align: center;
}

.order-table__delete-button {
  border: none;
  background: transparent;
  cursor: pointer;
  padding: 4px;
  border-radius: 50%;
  color: #5f6368;
  transition: background 0.2s ease, color 0.2s ease;

  &:hover {
    background: #fce8e6;
    color: #d93025;
  }
}

.order-table__add-row {
  background: #f8f9fa;
}

.order-table__add-row-button {
  width: 100%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 8px;
  border: 1px dashed #c1d4f7;
  background: #f1f3f4;
  color: #1a73e8;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s ease, border-color 0.2s ease;

  &:hover {
    background: #e8f0fe;
    border-color: #1a73e8;
  }
}

.order-table__add-row-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.order-table__add-row-text {
  white-space: nowrap;
}
</style>

